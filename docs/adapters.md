# Ingest adapters — bring your own protocol system

EtiqTech reviews one thing: a **canonical protocol instance** (the JSON contract in
[`docs/schema.md`](schema.md), defined in `src/schema.py`). The Israeli Council HTML export
is just the first source of that JSON. An institution running Cayuse, Topaz, Tick@lab, iRIS
or a home-grown form writes a small adapter that emits the canonical JSON — it never has to
read the HTML parser.

## Two ways in

| Route | What you send | Adapter |
|---|---|---|
| upload `.html`/`.htm`, or JSON body `{"html_content": "..."}` | the Council export | `il-council-html` (reference adapter, `src/html_to_json.py`) |
| upload `.json`, or JSON body `{"instance": {...}}` | a canonical instance | `canonical-json` — validated **strictly** against the schema; violations come back as `400` with `path: rule` messages (values are never echoed) |

Both `/api/analyze` and `/api/analyze-with-session` accept both; the response carries
`"adapter"` so you can see which one handled the input.

## Writing an adapter (outside the app)

The interface is a function from your data to the canonical dict. Start from the schema
skeleton (every required field, filled with schema examples) and overlay what you know:

```python
from src.adapters import schema_skeleton, item_skeleton, schema_errors

inst = schema_skeleton()                       # valid, minimal, required fields only
inst["header"].update(protocol_id="90042", institution="Example Institute")
exp = item_skeleton("experiments")             # one experiment, all required sub-fields
exp["animals"].update(species="mouse", n=24)
inst["experiments"] = [exp]
assert schema_errors(inst) == []               # what the server will check
```

A complete, runnable example is `examples/adapters/minimal_adapter.py` (a flat record →
canonical instance). Tests run it through validation and the linter.

## Registering an adapter inside the app

`src/adapters.py: ADAPTERS` maps a name to `Adapter(name, description, extensions, detect,
parse)`. `detect(text) -> bool` is used when the upload has no usable extension;
`parse(text) -> dict` returns the canonical instance (raise `IngestError` with a message safe
to show users — never include the content). Add an entry, and the upload routes accept the
new extension automatically.

## Vocabulary caveat (read this)

`docs/schema.md` ends with a measured **conformance** section: the reference adapter's own
output does not validate against the schema on any fixture, mainly because the Council export
carries Hebrew enum values (`נקבה`, `גרם`, `שבוע`, `המתה`) where the schema declares English
ones, and one required summary key is never produced. The linter is written against what the
parser emits. Until the maintainer decides whether to normalize the parser or widen the schema,
a third-party adapter that follows the schema literally is *valid* but will feed the linter
different vocabularies than the reference adapter does; where a check depends on a value
(sex, units, euthanasia method, fate), copy the reference adapter's values.
