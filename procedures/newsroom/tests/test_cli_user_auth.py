"""Native newsroom OAuth/session behavior; no real login, provider or keychain."""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from papyrus_content.cli_user_auth import AuthConfig, AuthError, OAuthError, Session, selected_headers, save_selection, KeychainStore


def token(now, subject='person-1', issuer='https://cognito-idp.us-east-1.amazonaws.com/pool', audience='native-client'):
    claims={'iss':issuer,'aud':audience,'sub':subject,'token_use':'id','exp':now+3600,'email':'person@example.test'}
    enc=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
    return enc({'alg':'RS256'})+'.'+enc(claims)+'.fixture-signature'


class MemoryStore:
    def __init__(self):self.data={}
    def get(self,key):return self.data.get(key)
    def set(self,key,value):self.data[key]=value
    def delete(self,key):self.data.pop(key,None)


class Provider:
    def __init__(self,clock):self.clock=clock;self.calls=[];self.failure=None;self.revocation_failure=False
    def post(self,url,fields):
        self.calls.append((url,fields))
        if self.failure:raise self.failure
        if url.endswith('/oauth2/revoke'):
            if self.revocation_failure:raise AuthError('Provider temporarily unavailable; retry later.')
            return {}
        return {'id_token':token(self.clock[0]),'refresh_token':'refresh-'+str(len(self.calls)), 'expires_in':3600}


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    monkeypatch.setenv('PAPYRUS_CLI_STATE_DIR',str(tmp_path/'state'))
    monkeypatch.delenv('PAPYRUS_GRAPHQL_AUTH',raising=False)
    config=AuthConfig(publication='https://news.example.test',issuer='https://cognito-idp.us-east-1.amazonaws.com/pool',client_id='native-client',oauth_domain='https://news.auth.us-east-1.amazoncognito.com',graphql_endpoint='https://abc.appsync-api.us-east-1.amazonaws.com/graphql',callback_uri='http://127.0.0.1:5182/oauth/callback',refresh_lifetime_seconds=172800)
    clock=[1000.0];store=MemoryStore();provider=Provider(clock);received={}
    def receive(callback,url,state,timeout):
        received.update(callback=callback,url=url,state=state,timeout=timeout)
        return 'one-time-code'
    session=Session(config,store=store,provider=provider,clock=lambda:clock[0],receive=receive)
    return config,clock,store,provider,received,session


def test_browser_login_uses_pkce_and_normal_user_identity(fixture):
    c,clock,store,p,seen,s=fixture
    identity=s.login()
    params=parse_qs(urlparse(seen['url']).query)
    assert params['response_type']==['code'] and params['identity_provider']==['Google']
    assert params['code_challenge_method']==['S256'] and params['state']==[seen['state']]
    fields=p.calls[0][1]
    assert fields['code']=='one-time-code' and fields['redirect_uri']==c.callback_uri
    assert fields['code_verifier'] not in seen['url']
    assert identity['subject']=='person-1' and identity['publication']==c.publication
    assert 'refresh' not in json.dumps(identity)
    assert json.loads(store.get(c.key))['refresh_token']=='refresh-1'


def test_renew_after_24_hours_and_process_restart_without_browser(fixture):
    c,clock,store,p,seen,s=fixture;s.login();clock[0]+=25*3600
    restarted=Session(c,store=store,provider=p,clock=lambda:clock[0],receive=lambda *a:pytest.fail('interactive login'))
    assert restarted.headers(c.graphql_endpoint)['Authorization']==token(clock[0])
    assert p.calls[-1][1]['grant_type']=='refresh_token'
    assert restarted.status()['elapsed_session_seconds']==25*3600
    assert restarted.status()['configured_refresh_lifetime_seconds']==172800
    assert restarted.status()['elapsed_24h_live_verified'] is False


def test_refresh_rotation_is_saved_before_next_process(fixture):
    c,clock,store,p,seen,s=fixture;s.login();clock[0]+=4000;s.headers(c.graphql_endpoint)
    rotated=json.loads(store.get(c.key))['refresh_token']
    second=Session(c,store=store,provider=p,clock=lambda:clock[0]);second.headers(c.graphql_endpoint)
    assert p.calls[-1][1]['refresh_token']==rotated


def test_transient_failure_preserves_session_and_does_not_open_browser(fixture):
    c,clock,store,p,seen,s=fixture;s.login();before=store.get(c.key);clock[0]+=4000
    p.failure=OAuthError('temporarily_unavailable',transient=True)
    with pytest.raises(AuthError,match='temporar'):s.headers(c.graphql_endpoint)
    assert store.get(c.key)==before


def test_confirmed_revocation_removes_secret_and_requires_login(fixture):
    c,clock,store,p,seen,s=fixture;s.login();clock[0]+=4000;p.failure=OAuthError('invalid_grant')
    with pytest.raises(AuthError,match='papyrus login'):s.headers(c.graphql_endpoint)
    assert store.get(c.key) is None


def test_publication_mismatch_is_rejected_before_any_refresh(fixture):
    c,clock,store,p,seen,s=fixture;s.login();before=len(p.calls)
    with pytest.raises(AuthError,match='publication'):s.headers('https://other.appsync-api.us-east-1.amazonaws.com/graphql')
    assert len(p.calls)==before


def test_logout_clears_local_secret_even_when_remote_revoke_is_unconfirmed(fixture):
    c,clock,store,p,seen,s=fixture;s.login();p.revocation_failure=True
    result=s.logout()
    assert result=={'local_session_removed':True,'remote_revocation':'unconfirmed'}
    assert store.get(c.key) is None
    with pytest.raises(AuthError,match='papyrus login'):s.headers(c.graphql_endpoint)


def test_logout_in_another_process_invalidates_cached_local_use(fixture):
    c,clock,store,p,seen,s=fixture;s.login()
    Session(c,store=store,provider=p,clock=lambda:clock[0]).logout()
    with pytest.raises(AuthError,match='papyrus login'):s.headers(c.graphql_endpoint)


def test_mismatched_issuer_audience_or_identity_is_never_saved(fixture):
    c,clock,store,p,seen,s=fixture
    for response in [token(clock[0],issuer='https://evil.test'),token(clock[0],audience='other')]:
        with patch.object(p,'post',return_value={'id_token':response,'refresh_token':'secret','expires_in':3600}):
            with pytest.raises(AuthError):s.login()
        assert store.get(c.key) is None


def test_no_plaintext_tokens_in_selection_file(fixture):
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    from papyrus_content.cli_user_auth import selection_path
    text=selection_path().read_text()
    assert 'refresh-1' not in text and token(clock[0]) not in text
    assert selection_path().stat().st_mode & 0o777==0o600


def test_selected_user_transport_never_calls_iam_on_expiry(fixture,monkeypatch):
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c);clock[0]+=4000;p.failure=OAuthError('invalid_grant')
    from papyrus_content import graphql_http
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    with patch.object(graphql_http,'iam_signed_graphql_headers',side_effect=AssertionError('IAM escalation')):
        with pytest.raises(AuthError):graphql_http.graphql_request_headers(endpoint=c.graphql_endpoint,body=b'{}')


def test_authoring_client_uses_same_user_transport(fixture,monkeypatch):
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    with patch('papyrus_content.graphql_http.iam_signed_graphql_headers',side_effect=AssertionError('IAM escalation')):
        headers=PapyrusGraphQLAuthoringClient(endpoint=c.graphql_endpoint)._request_headers(b'{}')
    assert headers['Authorization']==token(clock[0])


def test_explicit_iam_keeps_operator_auth_separate(fixture,monkeypatch):
    c,clock,store,p,seen,s=fixture;save_selection(c);monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH','iam')
    assert selected_headers(c.graphql_endpoint) is None


def test_secret_store_rejects_plaintext_backend():
    class Plaintext:
        __module__='keyrings.alt.file'
    with pytest.raises(AuthError,match='secure'):KeychainStore(backend=Plaintext())


def test_missing_native_configuration_is_actionable_and_does_not_open_browser(tmp_path):
    from papyrus_content.cli_user_auth import load_config
    with pytest.raises(AuthError,match='native OAuth'):load_config(tmp_path/'absent.json')


def test_refresh_errors_do_not_leak_provider_payload(fixture):
    from papyrus_content.cli_user_auth import HTTPProvider
    import urllib.error
    from io import BytesIO
    error=urllib.error.HTTPError('https://auth.test',400,'bad',{},BytesIO(b'{"error":"invalid_grant","error_description":"SECRET-TOKEN"}'))
    with patch('urllib.request.OpenerDirector.open',side_effect=error):
        with pytest.raises(AuthError) as result:HTTPProvider().post('https://auth.test/oauth2/token',{})
    assert 'SECRET' not in str(result.value)


def test_cli_login_and_status_are_real_dispatch_paths(fixture,capsys,monkeypatch):
    from papyrus import cli
    c,clock,store,p,seen,s=fixture
    monkeypatch.setattr('papyrus_content.cli_user_auth.resolve_config',lambda *a,**k:c)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    assert cli.main(['login','--publication',c.publication])==0
    assert cli.main(['whoami'])==0
    assert cli.main(['auth','status'])==0
    assert 'person-1' in capsys.readouterr().out


def test_concurrent_refresh_reads_latest_rotated_secret_under_shared_lock(fixture):
    from concurrent.futures import ThreadPoolExecutor
    import threading,time
    c,clock,store,p,seen,s=fixture;s.login();clock[0]+=4000
    original=p.post;barrier=threading.Barrier(2)
    def slow(*args):
        time.sleep(0.03)
        return original(*args)
    p.post=slow
    def renew(_):
        barrier.wait(timeout=3)
        return Session(c,store=store,provider=p,clock=lambda:clock[0]).headers(c.graphql_endpoint)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(renew,range(2))))==2
    assert p.calls[-2][1]['refresh_token']=='refresh-1'
    assert p.calls[-1][1]['refresh_token']=='refresh-2'
    assert json.loads(store.get(c.key))['refresh_token']=='refresh-3'


def test_actual_fresh_python_process_renews_synthetic_session_after_25_simulated_hours(fixture,tmp_path):
    import subprocess,sys,os
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    # Test-only synthetic store is deliberately not a production storage backend.
    file=tmp_path/'synthetic-secure-store.json';file.write_text(json.dumps(store.data))
    code=r'''
import json,os
from pathlib import Path
from unittest.mock import patch
from papyrus_content.cli_user_auth import Session,resolve_config
from procedures.newsroom.tests.test_cli_user_auth import MemoryStore,Provider
from papyrus import cli
clock=[1000+25*3600]
store=MemoryStore();store.data=json.loads(Path(os.environ['SYNTHETIC_STORE']).read_text())
provider=Provider(clock)
session=Session(resolve_config(),store=store,provider=provider,clock=lambda:clock[0],receive=lambda *a: (_ for _ in ()).throw(AssertionError('interactive login')))
with patch('papyrus_content.cli_user_auth.session_for',return_value=session):
    assert cli.main(['whoami'])==0
assert provider.calls[0][1]['grant_type']=='refresh_token'
'''
    environment=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[3]/'src')+os.pathsep+str(Path(__file__).resolve().parents[3]),SYNTHETIC_STORE=str(file))
    result=subprocess.run([sys.executable,'-c',code],env=environment,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    status=json.loads(result.stdout)
    assert status['subject']=='person-1' and status['elapsed_session_seconds']==90000
    assert status['elapsed_24h_live_verified'] is False
    assert 'refresh-1' not in result.stdout and 'fixture-signature' not in result.stdout


def test_user_mutation_with_uncertain_connection_is_not_replayed(fixture,monkeypatch):
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    from papyrus_content.operator_errors import GraphQLRequestError
    from unittest.mock import MagicMock
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    client=PapyrusGraphQLAuthoringClient(endpoint=c.graphql_endpoint)
    connection=MagicMock();connection.getresponse.side_effect=ConnectionResetError('uncertain delivery')
    with patch.object(client,'_open_connection',return_value=connection):
        with pytest.raises(GraphQLRequestError):client.graphql('mutation Save { updateItem(input:{id:"fixture"}) { id } }')
    assert connection.request.call_count==1


@pytest.mark.parametrize('status',[401,403])
def test_server_denial_is_not_replayed_or_reauthenticated(fixture,monkeypatch,status):
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    from papyrus_content.operator_errors import GraphQLRequestError
    from unittest.mock import MagicMock
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    connection=MagicMock();response=connection.getresponse.return_value
    response.status=status;response.reason='Forbidden';response.read.return_value=b'{"message":"denied"}'
    client=PapyrusGraphQLAuthoringClient(endpoint=c.graphql_endpoint)
    with patch.object(client,'_open_connection',return_value=connection):
        with pytest.raises(GraphQLRequestError) as error:client.graphql('query Private { getAssignment(id:"fixture") { id } }')
    assert connection.request.call_count==1
    assert 'aws sso' not in str(error.value) and 'papyrus auth status' in str(error.value)
    assert len(p.calls)==1


def test_cognito_refresh_need_not_return_a_new_refresh_token(fixture):
    c,clock,store,p,seen,s=fixture;s.login();clock[0]+=4000
    with patch.object(p,'post',return_value={'id_token':token(clock[0]),'expires_in':3600}):
        assert s.headers(c.graphql_endpoint)['Authorization']==token(clock[0])
    assert json.loads(store.get(c.key))['refresh_token']=='refresh-1'


def test_account_subject_must_not_change_on_refresh(fixture):
    c,clock,store,p,seen,s=fixture;s.login();before=store.get(c.key);clock[0]+=4000
    with patch.object(p,'post',return_value={'id_token':token(clock[0],subject='someone-else'),'expires_in':3600}):
        with pytest.raises(AuthError):s.headers(c.graphql_endpoint)
    assert store.get(c.key)==before


@pytest.mark.parametrize('lifetime',[float('nan'),float('inf'),-1,0])
def test_invalid_expiry_is_not_saved(fixture,lifetime):
    c,clock,store,p,seen,s=fixture
    with patch.object(p,'post',return_value={'id_token':token(clock[0]),'refresh_token':'fixture','expires_in':lifetime}):
        with pytest.raises(AuthError):s.login()
    assert store.get(c.key) is None


def test_selected_publication_can_switch_without_cross_reusing_tokens(fixture):
    from dataclasses import replace
    c,clock,store,p,seen,s=fixture;s.login()
    other=replace(c,publication='https://other.example.test',graphql_endpoint='https://other.appsync-api.us-east-1.amazonaws.com/graphql')
    assert c.key != other.key
    with pytest.raises(AuthError,match='papyrus login'):
        Session(other,store=store,provider=p,clock=lambda:clock[0]).headers(other.graphql_endpoint)


def test_lock_file_contains_no_secret(fixture):
    from papyrus_content.cli_user_auth import state_dir
    c,clock,store,p,seen,s=fixture;s.login()
    files=list(state_dir().glob('*.lock'))
    assert len(files)==1 and files[0].read_bytes()==b''
    assert files[0].stat().st_mode & 0o777==0o600


def test_failed_keychain_delete_cannot_report_successful_local_logout(fixture):
    c,clock,store,p,seen,s=fixture;s.login()
    with patch.object(store,'delete',side_effect=AuthError('locked')):
        with pytest.raises(AuthError,match='locked'):s.logout()


def test_callback_rejects_wrong_state_then_accepts_matching_callback():
    from papyrus_content.cli_user_auth import receive_code
    import socket,threading,urllib.request,urllib.error
    with socket.socket() as free:
        free.bind(('127.0.0.1',0));port=free.getsockname()[1]
    uri=f'http://127.0.0.1:{port}/oauth/callback';observed=[];threads=[]
    def browser(_):
        def visit():
            for state in ['wrong','expected']:
                try:
                    with urllib.request.urlopen(uri+'?state='+state+'&code=fixture-code',timeout=2) as response:observed.append(response.status)
                except urllib.error.HTTPError as error:observed.append(error.code)
        thread=threading.Thread(target=visit);thread.start();threads.append(thread);return True
    with patch('webbrowser.open',side_effect=browser):
        assert receive_code(uri,'https://auth.example.test','expected',2)=='fixture-code'
    for thread in threads:thread.join(timeout=3)
    assert observed==[400,200]


def test_login_timeout_is_bounded_and_does_not_store_a_session():
    from papyrus_content.cli_user_auth import receive_code
    import socket
    with socket.socket() as free:
        free.bind(('127.0.0.1',0));port=free.getsockname()[1]
    with patch('webbrowser.open',return_value=True):
        with pytest.raises(AuthError,match='timed out'):receive_code(f'http://127.0.0.1:{port}/','https://auth.test','state',0.01)


def test_oauth_provider_refuses_secret_bearing_redirects():
    from papyrus_content.cli_user_auth import HTTPProvider
    import urllib.request
    handlers=[]
    original=urllib.request.build_opener
    def build(*args):
        handlers.extend(args)
        class Opener:
            def open(self,*a,**k):raise urllib.error.HTTPError('https://auth.test',302,'redirect',{},None)
        return Opener()
    with patch('urllib.request.build_opener',side_effect=build):
        with pytest.raises(AuthError,match='rejected'):HTTPProvider().post('https://auth.test/oauth2/token',{'refresh_token':'synthetic'})
    assert handlers[0].redirect_request(None,None,None,None,None,None) is None


def test_native_keychain_duplicate_update_keeps_old_item_until_update():
    from papyrus_content.macos_keychain import MacOSKeychain
    from unittest.mock import MagicMock
    native=object.__new__(MacOSKeychain)
    native._dictionary=MagicMock(return_value=('fixture-dictionary',[]));native._release=MagicMock()
    native.sec=MagicMock();native.sec.SecItemAdd.return_value=-25299;native.sec.SecItemUpdate.return_value=0
    native.set_password('service','binding','synthetic-secret')
    assert native.sec.SecItemUpdate.call_count==1
    assert native.sec.SecItemDelete.call_count==0
    assert native._release.call_count==3


def test_native_keychain_locked_error_is_sanitized_and_no_fallback_occurs():
    from papyrus_content.macos_keychain import MacOSKeychain
    from unittest.mock import MagicMock
    native=object.__new__(MacOSKeychain)
    native.get_password=MagicMock(side_effect=RuntimeError('SYNTHETIC-SECRET-ERROR'))
    store=KeychainStore(backend=native)
    with pytest.raises(AuthError,match='unlock') as error:store.get('binding')
    assert 'SYNTHETIC' not in str(error.value)


def test_native_keychain_item_not_found_is_a_missing_session():
    from papyrus_content.macos_keychain import MacOSKeychain
    from unittest.mock import MagicMock
    native=object.__new__(MacOSKeychain)
    native._dictionary=MagicMock(return_value=('fixture-dictionary',[]));native._release=MagicMock()
    native.sec=MagicMock();native.sec.SecItemCopyMatching.return_value=-25300
    assert native.get_password('service','binding') is None
    native._release.assert_called_once()


def test_native_keychain_read_and_delete_use_sdk_results():
    import ctypes
    from papyrus_content.macos_keychain import MacOSKeychain
    from unittest.mock import MagicMock
    native=object.__new__(MacOSKeychain)
    native._dictionary=MagicMock(return_value=('fixture-dictionary',[]));native._release=MagicMock()
    native.sec=MagicMock();native.cf=MagicMock()
    data=ctypes.create_string_buffer(b'synthetic-secret')
    pointer=ctypes.cast(data,ctypes.c_void_p).value
    def copy(query,result):
        ctypes.cast(result,ctypes.POINTER(ctypes.c_void_p))[0]=pointer
        return 0
    native.sec.SecItemCopyMatching.side_effect=copy
    native.cf.CFDataGetBytePtr.return_value=pointer
    native.cf.CFDataGetLength.return_value=len(b'synthetic-secret')
    assert native.get_password('service','binding')=='synthetic-secret'
    native.cf.CFRelease.assert_called_once()
    native.sec.SecItemDelete.return_value=-25300
    native.delete_password('service','binding')
    native.sec.SecItemDelete.return_value=-25308
    with pytest.raises(RuntimeError,match='delete'):native.delete_password('service','binding')


def test_unknown_auth_mode_never_silently_selects_iam(fixture,monkeypatch):
    from papyrus_content import graphql_http
    c,*_=fixture;monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH','typo-user')
    with patch.object(graphql_http,'iam_signed_graphql_headers',side_effect=AssertionError('IAM escalation')):
        with pytest.raises(AuthError,match='Unknown PAPYRUS_GRAPHQL_AUTH'):
            graphql_http.graphql_request_headers(endpoint=c.graphql_endpoint,body=b'{}')


def test_public_login_metadata_does_not_authorize_server_roles(fixture,monkeypatch):
    from papyrus_content import graphql_http
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    with patch.object(graphql_http,'_aws_credentials',side_effect=AssertionError('AWS credential probe')):
        assert graphql_http.authoring_credentials_available()
        assert set(graphql_http.graphql_request_headers(endpoint=c.graphql_endpoint,body=b'{}'))=={'content-type','Authorization'}


def test_bad_stored_session_is_a_clean_error_not_a_traceback(fixture):
    c,clock,store,p,seen,s=fixture
    store.set(c.key,json.dumps({'subject':'person-1','refresh_token':'synthetic'}))
    with pytest.raises(AuthError,match='invalid'):s.headers(c.graphql_endpoint)


def test_missing_stored_identity_label_is_a_clean_status_error(fixture):
    c, clock, store, p, seen, session = fixture
    store.set(c.key, json.dumps({'subject':'person-1', 'refresh_token':'synthetic', 'created_at':1000}))
    with pytest.raises(AuthError, match='invalid'):
        session.status()


def test_explicit_new_person_login_invalidates_old_process_cached_identity(fixture):
    c,clock,store,p,seen,s=fixture;s.login()
    second=Session(c,store=store,provider=p,clock=lambda:clock[0],receive=lambda *a:'new-code')
    new={'id_token':token(clock[0],subject='person-2'),'refresh_token':'synthetic-new-person','expires_in':3600}
    with patch.object(p,'post',return_value=new):
        second.login()
        assert s.headers(c.graphql_endpoint)['Authorization']==new['id_token']
    assert s.status()['subject']=='person-2'


def test_logout_selected_session_cannot_downgrade_to_available_operator_identity(fixture,monkeypatch):
    from papyrus_content import graphql_http
    c,clock,store,p,seen,s=fixture;s.login();save_selection(c);s.logout()
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for',lambda config:s)
    with patch.object(graphql_http,'iam_signed_graphql_headers',side_effect=AssertionError('IAM escalation')):
        with pytest.raises(AuthError,match='papyrus login'):
            graphql_http.graphql_request_headers(endpoint=c.graphql_endpoint,body=b'{}')


def test_inaccessible_session_directory_is_a_clean_operator_error(fixture):
    from papyrus_content.cli_user_auth import state_dir
    with patch.object(Path, 'mkdir', side_effect=PermissionError('fixture denied')):
        with pytest.raises(AuthError, match='directory permissions'):
            state_dir()


def test_session_lock_refusal_never_uses_the_provider(fixture):
    c, clock, store, provider, seen, session = fixture
    session.login()
    previous_calls = len(provider.calls)
    with patch('papyrus_content.cli_user_auth.os.open', side_effect=PermissionError('fixture denied')):
        with pytest.raises(AuthError, match='session lock'):
            session.headers(c.graphql_endpoint)
    assert len(provider.calls) == previous_calls
