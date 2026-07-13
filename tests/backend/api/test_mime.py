import mimetypes

from stockroom.host.mime import register_web_mime_types, web_mime_type


def test_js_registers_as_javascript_even_if_registry_said_text_plain():
    # simulate the Windows trap: a prior mapping of .js to text/plain
    mimetypes.add_type("text/plain", ".js")
    register_web_mime_types()
    assert web_mime_type("bundle.js") == "text/javascript"
    assert web_mime_type("module.mjs") == "text/javascript"


def test_other_web_types_register():
    register_web_mime_types()
    assert web_mime_type("style.css") == "text/css"
    assert web_mime_type("data.json") == "application/json"
    assert web_mime_type("app.wasm") == "application/wasm"


def test_registration_is_idempotent():
    register_web_mime_types()
    register_web_mime_types()
    assert web_mime_type("x.js") == "text/javascript"
