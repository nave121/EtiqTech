import os
import sys
import json
import logging
import secrets
import threading
import uuid
from datetime import datetime, timedelta

# Add the parent directory to the path so we can import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, g, render_template, request, jsonify, Response, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import requests as http_requests

from src.html_to_json import parse_html
from src.linter_renderer import lint, render_html_with_refs
from src.llm_agent import law_loaded, run_verification_stream
from src.llm_clients import LLMError, local_first_status, ollama_base_url
from src.llm_layer3 import run_human_eye_stream

# ── Security note ──────────────────────────────────────────────────
# This server is designed to run locally. It has NO authentication.
# Do NOT expose it to the public internet without adding an auth layer
# (e.g. reverse proxy with basic auth, OAuth, or API key middleware).
# ───────────────────────────────────────────────────────────────────

# Logging is configured HERE (the entrypoint) and nowhere else. Default INFO:
# DEBUG would let urllib3/requests echo request internals, and no log level may
# ever carry protocol text (see PRIVACY invariants). LOG_LEVEL=DEBUG is opt-in.
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

_llm_target = local_first_status()
if _llm_target["remote"] and not _llm_target["remote_allowed"]:
    logger.error(
        "OLLAMA_BASE_URL points at a REMOTE host (%s) and ETIQTECH_ALLOW_REMOTE_LLM is not set. "
        "LLM calls will be refused so no protocol text leaves this machine; the linter still works.",
        _llm_target["ollama_host"],
    )
elif _llm_target["remote"]:
    logger.warning(
        "REMOTE LLM ENABLED: protocol text will be sent to %s (ETIQTECH_ALLOW_REMOTE_LLM=1). "
        "This deployment is NOT local-first. Make sure your privacy notice says so.",
        _llm_target["ollama_host"],
    )

if not law_loaded():
    logger.warning(
        "LAW TEXT NOT FOUND — resources/law/ is missing from this deployment; "
        "LLM review will run without law grounding. /api/health reports law_loaded=false."
    )

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
            static_folder=os.path.join(os.path.dirname(__file__), 'static'))

# Configure upload settings
ALLOWED_EXTENSIONS = {'html', 'htm'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# SECRET_KEY: required for session cookies and CSRF protection.
# In production, set SECRET_KEY env var to a stable random value.
_secret = os.getenv('SECRET_KEY')
if not _secret and os.getenv('FLASK_ENV') == 'production':
    raise ValueError("SECRET_KEY environment variable must be set in production")
app.config['SECRET_KEY'] = _secret or os.urandom(32).hex()

# RATELIMIT_ENABLED=false disables limiting (load tests, tests/test_gunicorn_sessions.py).
# It is the app's only DoS control, so it is refused in production and loud elsewhere.
app.config['RATELIMIT_ENABLED'] = os.getenv('RATELIMIT_ENABLED', 'true').lower() not in ('0', 'false', 'no')
if not app.config['RATELIMIT_ENABLED']:
    if os.getenv('FLASK_ENV') == 'production':
        raise ValueError("RATELIMIT_ENABLED=false is not allowed in production")
    logger.warning("Rate limiting DISABLED via RATELIMIT_ENABLED — never run like this in production")

# Behind a reverse proxy (Cloudflare Access, nginx) remote_addr is the proxy, so every
# user would share one rate-limit bucket. Set PROXY_FIX=1 to trust ONE hop of
# X-Forwarded-For. Leave it unset when clients reach gunicorn directly, or they can
# spoof the header to dodge the limiter.
if os.getenv('PROXY_FIX', '').lower() in ('1', 'true', 'yes'):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# NOTE: memory:// storage is per-process. With gunicorn.conf.py (1 worker) that is
# one shared counter; if the app is ever run with several workers or replicas,
# point storage_uri at a shared store (e.g. redis://) or limits become per-process.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)


@app.before_request
def issue_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)


@app.context_processor
def inject_csp_nonce():
    return {'csp_nonce': g.get('csp_nonce', '')}


@app.after_request
def set_security_headers(response):
    # Inline <script> blocks must carry nonce="{{ csp_nonce }}"; anything else inline is blocked.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{g.get('csp_nonce', '')}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = (
            'max-age=31536000; includeSubDomains'
        )
    return response


@app.before_request
def check_origin():
    """Block cross-origin POST requests (CSRF protection)."""
    if request.method != 'POST':
        return None
    origin = request.headers.get('Origin', '')
    if not origin:
        # No Origin header — same-origin requests from most browsers omit it
        return None
    allowed_origins = [
        'http://localhost:4242',
        'http://127.0.0.1:4242',
    ]
    custom = os.getenv('ALLOWED_ORIGINS', '')
    if custom:
        allowed_origins.extend(o.strip() for o in custom.split(','))
    if origin not in allowed_origins:
        return jsonify({'error': 'Forbidden — cross-origin request blocked'}), 403


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def landing():
    return render_template('landing.html')


@app.route('/app')
def analyzer():
    return render_template('app.html')


@app.route('/api/analyze', methods=['POST'])
@limiter.limit("10 per minute")
def analyze():
    """
    Analyze an uploaded Council HTML export.

    Accepts:
    - multipart/form-data with 'file' field containing HTML file
    - application/json with 'html_content' field containing raw HTML string

    Returns JSON:
    {
        "success": true/false,
        "rendered_html": "...",  # HTML with data-ref attributes
        "lint_report": {...},    # Full lint report
        "error": "..."           # Only present on failure
    }
    """
    try:
        html_content = None

        # Handle file upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({
                    'success': False,
                    'error': 'No file selected'
                }), 400

            if not allowed_file(file.filename):
                return jsonify({
                    'success': False,
                    'error': 'Invalid file type. Please upload an HTML file.'
                }), 400

            html_content = file.read().decode('utf-8')

        # Handle JSON body with raw HTML
        elif request.is_json:
            data = request.get_json()
            html_content = data.get('html_content')
            if not html_content:
                return jsonify({
                    'success': False,
                    'error': 'Missing html_content in request body'
                }), 400

        else:
            return jsonify({
                'success': False,
                'error': 'Please upload an HTML file or provide html_content in JSON body'
            }), 400

        # Parse HTML to JSON instance
        instance = parse_html(html_content)

        # Run linter
        lint_report = lint(instance, profile='default')

        # Render HTML with data-ref attributes for error mapping
        rendered_html = render_html_with_refs(instance)

        return jsonify({
            'success': True,
            'rendered_html': rendered_html,
            'lint_report': lint_report
        })

    except UnicodeDecodeError:
        return jsonify({
            'success': False,
            'error': 'Could not decode file. Please ensure the file is UTF-8 encoded.'
        }), 400
    except Exception as e:
        logger.error("Analysis failed", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'Analysis failed. Please try again.'
        }), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check. law_loaded=false means the runtime law corpus is missing (see resources/law/)."""
    target = local_first_status()
    return jsonify({
        'status': 'ok',
        'law_loaded': law_loaded(),
        'llm_local': not target['remote'],
        'llm_remote_allowed': target['remote_allowed'],
    })


# Store analysis results temporarily for LLM verification.
# In-memory only, ~1h TTL, never written to disk (see PRIVACY.md). Mutated from
# many gthread threads, so every read/write of the dict goes through _cache_lock.
_analysis_cache = {}
_cache_lock = threading.Lock()
MAX_SESSIONS = 100


def _cleanup_expired_sessions(max_age_hours=1):
    """Remove sessions older than max_age_hours. Caller holds _cache_lock."""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    expired = [
        key
        for key, value in _analysis_cache.items()
        if value.get('created_at', datetime.min) < cutoff
    ]
    for key in expired:
        del _analysis_cache[key]


def _store_session(entry):
    session_id = str(uuid.uuid4())
    with _cache_lock:
        _cleanup_expired_sessions()
        _analysis_cache[session_id] = entry
        # Cap total sessions as a safety net (dicts keep insertion order: oldest first)
        for k in list(_analysis_cache.keys())[:-MAX_SESSIONS]:
            del _analysis_cache[k]
    return session_id


def _get_session(session_id):
    with _cache_lock:
        return _analysis_cache.get(session_id)


def _update_session(session_id, **fields):
    """Write back into a session if it still exists; a no-op if it was evicted mid-stream."""
    with _cache_lock:
        entry = _analysis_cache.get(session_id)
        if entry is not None:
            entry.update(fields)


@app.route('/api/ollama-models')
def ollama_models():
    """Proxy Ollama /api/tags to list available models."""
    try:
        base_url = ollama_base_url()  # same local-first gate as the LLM calls
        resp = http_requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = sorted(
            [m["name"] for m in data.get("models", [])],
            key=str.lower,
        )
        return jsonify({"success": True, "models": models})
    except Exception as e:
        logger.error("Ollama health check failed", exc_info=True)
        return jsonify({
            "success": False,
            "models": [],
            "error": "LLM service unavailable"
        })


@app.route('/api/analyze-with-session', methods=['POST'])
@limiter.limit("10 per minute")
def analyze_with_session():
    """
    Same as /api/analyze but stores the result for subsequent LLM verification.
    Returns a session_id to use with /api/llm-verify-stream.
    """
    try:
        html_content = None

        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400
            if not allowed_file(file.filename):
                return jsonify({'success': False, 'error': 'Invalid file type'}), 400
            html_content = file.read().decode('utf-8')
        elif request.is_json:
            data = request.get_json()
            html_content = data.get('html_content')
            if not html_content:
                return jsonify({'success': False, 'error': 'Missing html_content'}), 400
        else:
            return jsonify({'success': False, 'error': 'Please upload an HTML file'}), 400

        instance = parse_html(html_content)
        lint_report = lint(instance, profile='default')
        rendered_html = render_html_with_refs(instance)

        # Read optional LLM provider/model from form data
        provider = request.form.get('provider', '').strip() or None
        model = request.form.get('model', '').strip() or None

        session_id = _store_session({
            'instance': instance,
            'lint_report': lint_report,
            'provider': provider,
            'model': model,
            'created_at': datetime.now(),
        })

        return jsonify({
            'success': True,
            'session_id': session_id,
            'rendered_html': rendered_html,
            'lint_report': lint_report
        })

    except Exception as e:
        logger.error("Analysis with session failed", exc_info=True)
        return jsonify({'success': False, 'error': 'Analysis failed. Please try again.'}), 500


@app.route('/api/llm-verify-stream/<session_id>')
def llm_verify_stream(session_id):
    """
    Stream LLM verification results using Server-Sent Events.

    Events:
    - theme_start: Starting analysis of a theme
    - token: A token from the LLM response
    - theme_done: Theme analysis complete with result
    - complete: All themes done, final result
    - error: An error occurred
    """
    cached = _get_session(session_id)
    if cached is None:
        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
        return Response(error_gen(), mimetype='text/event-stream')

    instance = cached['instance']
    lint_report = cached['lint_report']

    provider = cached.get('provider')
    model = cached.get('model')

    def generate():
        try:
            for event in run_verification_stream(
                instance, lint_report, stance='committee',
                provider=provider, model=model,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                # Save the final layer2 result so human-eye-stream can access it
                if event.get("type") == "complete":
                    _update_session(session_id, layer2_result=event.get("result"))
        except Exception as e:
            logger.error("LLM verification streaming error", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Verification failed. Check server logs.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/human-eye-stream/<session_id>')
def human_eye_stream(session_id):
    """
    Stream Layer 3 "Human Eye" holistic review using Server-Sent Events.

    Must be called after /api/llm-verify-stream has completed (or independently).
    Layer 2 result is read from the session cache if available.

    Events:
    - layer3_trigger: Layer 3 triggered with reason
    - layer3_skip: trigger conditions not met
    - pass_start: starting a review pass
    - token: a token from the LLM response
    - pass_done: pass complete with structured result
    - complete: final HumanEyeResult
    - error: an error occurred
    """
    cached = _get_session(session_id)
    if cached is None:
        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
        return Response(error_gen(), mimetype='text/event-stream')

    instance = cached['instance']
    lint_report = cached['lint_report']
    layer2_result = cached.get('layer2_result')

    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    provider = cached.get('provider')
    model = cached.get('model')

    def generate():
        try:
            for event in run_human_eye_stream(
                instance, lint_report, layer2_result, force=force,
                provider=provider, model=model,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("Layer 3 streaming error", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Review failed. Check server logs.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'false').lower() in ('1', 'true')
    app.run(debug=debug, port=4242)
