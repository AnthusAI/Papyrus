"""Privacy-safe GA4 events and page-location redaction for pages that set ``SiteChrome.ga_measurement_id``.

Two inline scripts, both emitted only when a measurement id is set:

* the redaction script runs before ``gtag('config')`` and sets ``page_location`` and ``page_referrer`` to
  versions with identity-bearing query parameters, opaque tokens, e-mail addresses and the fragment removed;
* the events script defines ``window.papyrusAnalytics.track(name, params)``, which sends only the reserved
  events below with only their listed parameters, and reports ``cta_click`` for links marked
  ``data-cta-location``.

Reserved events and their parameters:

``cta_click``          ``cta_text``, ``cta_location``, ``link_url`` (host and path only)
                       (links marked ``data-cta-location``, and links to ``anth.us/engage`` whose ``cta`` query value is the location)
``sign_up``            ``method``                      (call only after the server confirmed the sign-up)
``generate_lead``      ``form_id``, ``lead_source``, ``solution``   (call only after the server confirmed the form)
``view_promotion`` / ``select_promotion``
                       ``promotion_id``, ``promotion_name``, ``creative_name``, ``location_id``
                       (reserved for sponsor units; nothing in the engine fires them)

Links inside an element with ``data-promotion-id`` never report ``cta_click``: a sponsor unit is a promotion.
Every value is trimmed to 100 characters, and a value that looks like an e-mail address, a ``ss1_`` subject
or a long opaque token is dropped. Nothing here can set ``user_id`` or any other parameter.
"""

from __future__ import annotations

_IDENTITY_PATTERNS = (
    "var IDENTITY_NAME=/^(token|t|ss|sitesubject|subject|email|e|handle|user|userid|user_id|uid|person|personid|person_id|"
    "key|code|secret|auth|session|sid|jwt)$/i;"
    "var IDENTITY_VALUE=/^ss1_|@|^[A-Za-z0-9._~-]{32,}$/;"
    "var IDENTITY_SEGMENT=/ss1_[A-Za-z0-9_-]+|[^\\/\\s@]+@[^\\/\\s]+/g;"
)


def render_location_redaction_script() -> str:
    # The inner function pushes its own ``arguments`` object, which is what gtag.js reads (an array would be ignored);
    # it does not depend on ``gtag`` being defined yet, so this script can precede the consent defaults and the config.
    return (
        "<script>(function(){window.dataLayer=window.dataLayer||[];" + _IDENTITY_PATTERNS +
        "function clean(raw,fallback){if(!raw)return raw;try{var u=new URL(raw),drop=[];"
        "u.searchParams.forEach(function(v,k){if(IDENTITY_NAME.test(k)||IDENTITY_VALUE.test(v))drop.push(k)});"
        "drop.forEach(function(k){u.searchParams.delete(k)});"
        "u.pathname=u.pathname.replace(IDENTITY_SEGMENT,'redacted');u.hash='';return u.toString()}"
        "catch(e){return fallback}}\n"
        "(function(){window.dataLayer.push(arguments)})('set',{page_location:clean(location.href,location.origin+location.pathname),"
        "page_referrer:clean(document.referrer,'')})})();</script>"
    )


_RESERVED_EVENTS = (
    "var EVENTS={cta_click:['cta_text','cta_location','link_url'],sign_up:['method'],"
    "generate_lead:['form_id','lead_source','solution'],"
    "view_promotion:['promotion_id','promotion_name','creative_name','location_id'],"
    "select_promotion:['promotion_id','promotion_name','creative_name','location_id']};"
)


def render_analytics_events_script() -> str:
    return (
        "<script>(function(){" + _IDENTITY_PATTERNS + _RESERVED_EVENTS +
        "var LOCATION=/^[a-z0-9_-]{1,40}$/;"
        "function text(v){return String(v==null?'':v).replace(/\\s+/g,' ').trim().slice(0,100)}"
        "function destination(v){return text(v.replace(/^[a-z][a-z0-9+.-]*:\\/\\//i,'').replace(/[?#].*$/,'')"
        ".replace(IDENTITY_SEGMENT,'redacted'))}\n"
        "function track(name,params){var allowed=EVENTS.hasOwnProperty(name)?EVENTS[name]:null;"
        "if(!allowed||typeof gtag!=='function'||!params)return false;var clean={};"
        "allowed.forEach(function(key){if(params[key]==null)return;"
        "var v=key==='link_url'?destination(String(params[key])):text(params[key]);"
        "if(key==='cta_location'&&!LOCATION.test(v))v='page';"
        "if(v&&!IDENTITY_VALUE.test(v))clean[key]=v});"
        "if(name==='cta_click')clean.transport_type='beacon';"
        "try{gtag('event',name,clean);return true}catch(e){return false}}\n"
        "window.papyrusAnalytics={track:track};\n"
        "function engage(u){return /(^|\\.)anth\\.us$/.test(u.hostname)&&/^\\/engage(\\/|$)/.test(u.pathname)}\n"
        "function onActivate(event){var a=event.target&&event.target.closest?event.target.closest('a[href]'):null;"
        "if(!a||a.closest('[data-promotion-id]'))return;var u;try{u=new URL(a.href,location.href)}catch(e){return}"
        "var place=a.getAttribute('data-cta-location');if(place==null){if(!engage(u))return;place=u.searchParams.get('cta')||'page'}"
        "track('cta_click',{cta_text:a.getAttribute('data-cta-text')||(a.textContent||'').replace(/\\s*\\u2192\\s*$/,''),"
        "cta_location:place,link_url:u.hostname+u.pathname})}\n"
        "document.addEventListener('click',onActivate);document.addEventListener('auxclick',onActivate)})();</script>"
    )
