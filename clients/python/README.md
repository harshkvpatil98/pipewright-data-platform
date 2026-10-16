# Pipewright's Python client and command line

Script Pipewright without reading its source: every API operation as a
Python method, and a `pipewright` command for the jobs people do most.

```sh
pip install -e clients/python        # from a checkout of the repository
pipewright login https://pipewright.example.com --token pw_...
pipewright projects
pipewright upload "Regional sales" orders.csv --name Orders --wait
pipewright run workflow "Regional sales" Nightly --wait
pipewright download "Regional sales" Orders -o orders.csv
pipewright bundle export "Regional sales" -o sales.json
pipewright convert "Regional sales" shop.zip --preview   # a dbt project, an Airflow workflow, a .yxmd ...
pipewright api GET /api/v1/projects
```

Make the token under **Your settings → API tokens**; a read token can look
but not change anything. `PIPEWRIGHT_URL` and `PIPEWRIGHT_TOKEN` override
what `login` saved (in `~/.config/pipewright/config.json`, readable by you
only). Run any command with `--help` for its options, and put `--json` first
for the API's own answers.

In Python:

```python
from pipewright import Client, PipewrightError

client = Client("https://pipewright.example.com", token="pw_...")
project = client.project_id("Regional sales")
answer = client.upload(project, "orders.csv", name="Orders")
client.wait_for_run(project, answer["run"]["id"])
for dataset in client.get_project_datasets(project)["items"]:
    print(dataset["name"], dataset["row_count"])
```

Every method is documented with the request it makes. They are generated
from the API's OpenAPI document by `scripts/generate-client.py`; a test
fails when the API changes and the client has not been regenerated.
