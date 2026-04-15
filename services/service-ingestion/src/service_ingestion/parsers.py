from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError


@dataclass(slots=True)
class ParsedTabularData:
    dataframe: pd.DataFrame
    metadata: dict[str, Any]


def parse_tabular_file(*, file_bytes: bytes, file_type: str) -> ParsedTabularData:
    if file_type == 'csv':
        return _parse_csv(file_bytes)
    if file_type == 'xlsx':
        return _parse_xlsx(file_bytes)
    if file_type == 'json':
        return _parse_json(file_bytes)
    raise BadRequestError('Unsupported file type for parsing.')


def _parse_csv(file_bytes: bytes) -> ParsedTabularData:
    last_error: Exception | None = None
    for encoding in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            dataframe = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
            return ParsedTabularData(
                dataframe=_normalize_dataframe(dataframe),
                metadata={'format': 'csv', 'encoding': encoding},
            )
        except UnicodeDecodeError as exc:
            last_error = exc
        except pd.errors.EmptyDataError as exc:
            raise BadRequestError('CSV file is empty.') from exc
        except pd.errors.ParserError as exc:
            raise BadRequestError(f'Unable to parse CSV file: {exc}') from exc
    raise BadRequestError(f'Unable to decode CSV file: {last_error}') from last_error


def _parse_json(file_bytes: bytes) -> ParsedTabularData:
    try:
        payload = json.loads(file_bytes.decode('utf-8'))
    except Exception as exc:
        raise BadRequestError(f'Unable to parse JSON file: {exc}') from exc

    if isinstance(payload, dict):
        records = [payload]
    elif isinstance(payload, list):
        if any(not isinstance(item, dict) for item in payload):
            raise BadRequestError('JSON arrays must contain objects for tabular ingestion.')
        records = payload
    else:
        raise BadRequestError('JSON upload must be an object or an array of objects.')

    if not records:
        raise BadRequestError('JSON file is empty.')

    dataframe = pd.json_normalize(records, sep='.')
    return ParsedTabularData(
        dataframe=_normalize_dataframe(dataframe),
        metadata={'format': 'json', 'record_count': len(records)},
    )


def _parse_xlsx(file_bytes: bytes) -> ParsedTabularData:
    try:
        workbook = pd.ExcelFile(io.BytesIO(file_bytes), engine='openpyxl')
    except ValueError as exc:
        raise BadRequestError(f'Unable to open Excel file: {exc}') from exc
    except Exception as exc:
        raise BadRequestError(f'Unable to open Excel file: {exc}') from exc

    if not workbook.sheet_names:
        raise BadRequestError('Excel file does not contain a worksheet.')

    sheet_name = workbook.sheet_names[0]
    try:
        dataframe = workbook.parse(sheet_name=sheet_name)
    except ValueError as exc:
        raise BadRequestError(f'Unable to parse Excel file: {exc}') from exc

    if dataframe.empty and len(dataframe.columns) == 0:
        raise BadRequestError('Excel file is empty.')

    return ParsedTabularData(
        dataframe=_normalize_dataframe(dataframe),
        metadata={
            'format': 'xlsx',
            'sheet_name': sheet_name,
            'sheet_count': len(workbook.sheet_names),
            'additional_sheets_ignored': max(len(workbook.sheet_names) - 1, 0),
        },
    )


def _normalize_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    normalized.columns = [
        str(column).strip() if str(column).strip() else f'column_{index + 1}'
        for index, column in enumerate(normalized.columns)
    ]
    normalized = normalized.where(pd.notna(normalized), None)
    return normalized
