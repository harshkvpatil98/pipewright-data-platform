from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from service_destinations.connectors.power_bi_publish import publish_dataframe_power_bi_push
from shared_python.errors import BadRequestError


def test_publish_rejects_empty_dataframe() -> None:
    df = pd.DataFrame({"a": []})
    with pytest.raises(BadRequestError, match="no rows"):
        publish_dataframe_power_bi_push(
            power_bi_config={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
            workspace_id=str(uuid.uuid4()),
            target_dataset_name="D",
            target_table_name="PublishedData",
            df=df,
            write_mode="replace",
        )


@patch("service_destinations.connectors.power_bi_publish.fetch_power_bi_access_token", return_value="tok")
@patch("service_destinations.connectors.power_bi_publish.httpx.Client")
def test_publish_replace_creates_dataset(mock_client_cls, _token) -> None:
    ws = str(uuid.uuid4())
    df = pd.DataFrame({"col a": [1, 2], "b": ["x", "y"]})

    mock_resp_list = MagicMock()
    mock_resp_list.raise_for_status = MagicMock()
    mock_resp_list.json.return_value = {"value": []}

    mock_resp_create = MagicMock()
    mock_resp_create.raise_for_status = MagicMock()
    mock_resp_create.json.return_value = {"id": "new-dataset-id"}

    mock_resp_post_rows = MagicMock()
    mock_resp_post_rows.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp_list
    mock_client.post.side_effect = [mock_resp_create, mock_resp_post_rows]
    mock_client_cls.return_value = mock_client

    out = publish_dataframe_power_bi_push(
        power_bi_config={"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        workspace_id=ws,
        target_dataset_name="MyDataset",
        target_table_name="PublishedData",
        df=df,
        write_mode="replace",
    )
    assert out.dataset_id == "new-dataset-id"
    assert out.rows_published == 2
    assert out.publish_mode == "created"
    mock_client.delete.assert_not_called()
