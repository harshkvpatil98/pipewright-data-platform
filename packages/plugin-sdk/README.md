# pipewright-plugin-sdk

What a Pipewright plugin is made of (SDK 1): tools for the Studio, formula
functions, chart types and connectors, declared in Python with no dependency
outside the standard library.

```python
from pipewright_plugin_sdk import Example, Plugin, Tool

plugin = Plugin(
    name="acme",
    version="1.0.0",
    publisher="Acme Ltd",
    description="Tools Acme's analysts use every day.",
    tools=(
        Tool(
            name="shout",
            title="Shout",
            summary="Capitals and an exclamation mark.",
            transform=lambda value, settings: f"{str(value).upper()}!",
            accepts="text",
            returns="text",
            example=Example(values=("hello",), expect=("HELLO!",)),
        ),
    ),
)
```

Name it under the `pipewright.plugins` entry point, check it with
`pipewright plugin check`, and enable it on a server with `PLUGINS_ENABLED`.
`pipewright plugin new <name>` writes a working plugin to start from. The
whole guide is in Pipewright's help, under **Using the API → Plugins**.
