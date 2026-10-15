"""Optional same-origin Papyrus curation BFF; host-owned session and storage.

The resolver supplies an original-session-pinned context. Browser scope headers
are expectations, never authority. This module creates no engine, store, grant,
credential or deployment. A remote transport must target the guarded publication
host, not the legacy unguarded local contract host.
"""
import asyncio
from dataclasses import dataclass
import inspect
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from decision_flywheel.publication_lab import CAPABILITIES, PublicationError
from .publication_bff import PublicationSelection

MAX_BYTES = 4_000_000


class BoundedBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > MAX_BYTES:
                return await JSONResponse({'error': 'curation request exceeds size limit'}, status_code=413,
                                          headers={'Cache-Control': 'no-store'})(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, bounded_receive, send)


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


def public_scope(selection):
    return {'accountId': selection.account_id, 'publicationId': selection.publication_id,
            'bindingRevision': selection.binding_revision}


@dataclass(frozen=True)
class CurationContext:
    selection: PublicationSelection
    mode: str
    authorize: object
    publication: object
    priming: object
    list_id: str
    classifiers: tuple
    capabilities: tuple = ('read',)
    binding_ref: object = None

    def __post_init__(self):
        if not isinstance(self.selection, PublicationSelection) or self.mode not in ('embedded', 'remote'):
            raise ValueError('verified curation selection and supported mode required')
        if not callable(self.authorize) or not self.list_id or not self.classifiers:
            raise ValueError('fresh authority and explicit priming contract required')

    async def guard(self, capability):
        try:
            current = await resolved(self.authorize(capability))
        except PublicationError:
            raise
        except Exception:
            raise PublicationError('curation authorization unavailable', 503) from None
        if current != self.selection:
            raise PublicationError('original curation session changed', 409, code='account_changed')


class EmbeddedPublicationTransport:
    """Preserve the existing BFF's fresh post-lock authority for direct execution."""
    def __init__(self, bff, connection):
        self.bff, self.connection = bff, connection

    async def command(self, selection, operation, payload, guard):
        access = await self.bff(self.connection, selection.publication_id, CAPABILITIES[operation])

        async def owned_guard():
            await guard()
            await resolved(access.execution_guard())

        return await access.lab.command(access.actor, selection.publication_id, operation,
                                        payload, execution_guard=owned_guard)


class RemotePublicationTransport:
    """Configured server-to-server HTTP client; remote host repeats its own guard."""
    def __init__(self, client):
        self.client = client

    async def command(self, selection, operation, payload, guard):
        await guard()
        if self.client.account_id != selection.account_id:
            raise PublicationError('remote client account mismatch', 409, code='account_changed')
        return await self.client.command(selection.publication_id, operation, payload)


class GuardedPrimingService:
    """Shared service behind the selected owner's execution boundary.

    The service/storage and execution factory are injected. Local SQLite is
    appropriate for an embedded review workspace, not a hosted S3 substitute.
    """
    def __init__(self, service, execution):
        self.service, self.execution = service, execution

    async def call(self, method, args, kwargs, guard):
        async with self.execution(execution_guard=guard):
            return await asyncio.to_thread(getattr(self.service, method), *args, **kwargs)


class RemotePrimingTransport:
    """Configured guarded BFF peer; no browser-supplied URL or identity."""
    def __init__(self, client, selection):
        self.client, self.selection = client, selection

    async def call(self, method, args, kwargs, guard):
        await guard()
        if method in ('contract', 'template'):
            variables = {'list': args[0], 'refs': args[1]}
            field = 'primingContract' if method == 'contract' else 'primingTemplate'
            query = 'query($list:ID!,$refs:JSON!){primingContract(listId:$list,classifiers:$refs)}'
            if method == 'template':
                variables['format'] = args[2]
                query = 'query($list:ID!,$refs:JSON!,$format:String!){primingTemplate(listId:$list,classifiers:$refs,format:$format)}'
        elif method == 'get':
            field = 'primingDraft'
            query = 'query($id:String!){primingDraft(identifier:$id)}'
            variables = {'id': args[0]}
        else:
            action = {'start_file': 'file', 'start_transform': 'transform', 'poll': 'poll',
                      'feedback': 'feedback', 'cancel': 'cancel', 'accept': 'accept'}.get(method)
            if action is None:
                raise PublicationError('unknown remote priming operation', 400)
            field = 'primingCommand'
            query = 'mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}'
            variables = {'action': action, 'payload': kwargs}
        expected = {'X-Cyclotron-Account': self.selection.account_id,
                    'X-Papyrus-Publication': self.selection.publication_id,
                    'X-Papyrus-Binding': self.selection.binding_revision}
        response = await self.client.post('/api/newsroom/curation/priming', json={'query': query, 'variables': variables},
                                          headers=expected, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > MAX_BYTES * 2:
            raise PublicationError('remote priming request failed; check outcome before retrying', 503)
        if any(response.headers.get(name) != value for name, value in expected.items()):
            raise PublicationError('remote priming response scope mismatch', 502)
        value = response.json()
        if value.get('errors') or not isinstance(value.get('data'), dict) or field not in value['data']:
            raise PublicationError('remote priming request refused', 409)
        return value['data'][field]


def checked_contract(context, list_id, classifiers):
    if str(list_id) != context.list_id or classifiers != list(context.classifiers):
        raise PublicationError('priming contract is outside the selected publication', 403)


def checked_draft(context, draft):
    contract = draft.get('contract', {})
    refs = [{'id': row['id'], 'revision': row['revision']} for row in contract.get('classifiers', [])]
    checked_contract(context, contract.get('list_id'), refs)
    return draft


async def priming_call(info, method, args=(), kwargs=None, capability='read'):
    context = info.context['curation']
    if context.priming is None:
        raise PublicationError('priming is not configured for this workspace', 503)
    await context.guard(capability)
    result = await context.priming.call(method, args, kwargs or {}, lambda: context.guard(capability))
    await context.guard(capability)
    return result


@strawberry.type
class PrimingQuery:
    @strawberry.field
    async def priming_contract(self, info: strawberry.Info, list_id: strawberry.ID, classifiers: JSON) -> JSON:
        checked_contract(info.context['curation'], list_id, classifiers)
        return await priming_call(info, 'contract', (str(list_id), classifiers))

    @strawberry.field
    async def priming_template(self, info: strawberry.Info, list_id: strawberry.ID, classifiers: JSON, format: str) -> JSON:
        checked_contract(info.context['curation'], list_id, classifiers)
        return await priming_call(info, 'template', (str(list_id), classifiers, format))

    @strawberry.field
    async def priming_draft(self, info: strawberry.Info, identifier: str) -> JSON:
        context = info.context['curation']
        return checked_draft(context, await priming_call(info, 'get', (identifier,)))


@strawberry.type
class PrimingMutation:
    @strawberry.mutation
    async def priming_command(self, info: strawberry.Info, action: str, payload: JSON) -> JSON:
        context = info.context['curation']
        methods = {'file': 'start_file', 'transform': 'start_transform', 'poll': 'poll',
                   'feedback': 'feedback', 'cancel': 'cancel', 'accept': 'accept'}
        if action not in methods or not isinstance(payload, dict):
            raise PublicationError('unknown priming operation', 400)
        if action in ('file', 'transform'):
            checked_contract(context, payload.get('list_id'), payload.get('refs'))
        else:
            # Scope check happens before any mutation, including cancellation.
            checked_draft(context, await priming_call(info, 'get', (payload.get('identifier'),), capability='review'))
        result = await priming_call(info, methods[action], kwargs=payload, capability='review')
        return checked_draft(context, result)


def create_curation_host(resolve_context):
    """Compose only when the host supplies verified original-session authority."""
    app = FastAPI()
    schema = strawberry.Schema(query=PrimingQuery, mutation=PrimingMutation)

    @app.middleware('http')
    async def boundary(request, next_handler):
        try:
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                raise PublicationError('cross-origin curation access refused', 403)
            if request.method == 'POST':
                if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                    raise PublicationError('JSON request required', 415)
                if len(await request.body()) > MAX_BYTES:
                    raise PublicationError('curation request exceeds size limit', 413)
            context = await resolved(resolve_context(request))
            if not isinstance(context, CurationContext):
                raise PublicationError('verified original session required', 401)
            request.state.curation = context
            if request.method == 'POST':
                expected = {'x-cyclotron-account': context.selection.account_id,
                            'x-papyrus-publication': context.selection.publication_id,
                            'x-papyrus-binding': context.selection.binding_revision}
                if any(not request.headers.get(name) for name in expected):
                    raise PublicationError('expected curation scope pins required', 400)
                if any(request.headers[name] != value for name, value in expected.items()):
                    raise PublicationError('selected curation scope changed', 409, code='account_changed')
            await context.guard('read')
            response = await next_handler(request)
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                     'X-Cyclotron-Account': context.selection.account_id,
                                     'X-Papyrus-Publication': context.selection.publication_id,
                                     'X-Papyrus-Binding': context.selection.binding_revision})
            return response
        except PublicationError as error:
            return JSONResponse({'error': str(error), 'code': error.code}, status_code=error.status,
                                headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'error': 'curation host unavailable'}, status_code=503,
                                headers={'Cache-Control': 'no-store'})

    @app.get('/api/newsroom/curation/context')
    async def context(request: Request):
        current = request.state.curation
        return {'scope': public_scope(current.selection), 'mode': current.mode,
                'priming': {'listId': current.list_id, 'classifiers': list(current.classifiers)} if current.priming else None,
                'capabilities': list(current.capabilities), 'bindingRef': current.binding_ref}

    @app.post('/api/newsroom/curation/publication')
    async def publication(request: Request):
        current = request.state.curation
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'operation', 'payload'} or body['operation'] not in CAPABILITIES or not isinstance(body['payload'], dict):
                raise PublicationError('explicit publication operation required', 400)
            if current.publication is None:
                raise PublicationError('publication execution is not configured', 503)
            capability = CAPABILITIES[body['operation']]
            await current.guard(capability)
            result = await current.publication.command(current.selection, body['operation'], body['payload'], lambda: current.guard(capability))
            await current.guard(capability)
            if not isinstance(result, dict) or result.get('contractVersion') != 'cyclotron-publication/v1' or any(result.get(key) != value for key, value in public_scope(current.selection).items()):
                raise PublicationError('publication response scope mismatch', 502)
            return result
        except PublicationError as error:
            return JSONResponse({'error': str(error), 'code': error.code}, status_code=error.status)
        except (ValueError, TypeError, KeyError):
            return JSONResponse({'error': 'invalid publication request'}, status_code=400)

    async def graphql_context(request: Request):
        return {'curation': request.state.curation}

    app.include_router(GraphQLRouter(schema, context_getter=graphql_context, graphql_ide=None,
                                     allow_queries_via_get=False), prefix='/api/newsroom/curation/priming')
    app.add_middleware(BoundedBody)
    return app
