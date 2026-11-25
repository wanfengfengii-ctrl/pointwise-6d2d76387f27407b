from dataclasses import dataclass
import hashlib
import json


V1_VERSION = 1


@dataclass(frozen=True)
class V1Envelope:
    issue_number: int
    body: dict
    checksum: str
    version: int = V1_VERSION


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False
    ).encode('ascii')


def body_checksum(body: dict) -> str:
    return hashlib.sha256(_canonical(body)).hexdigest()


def _check_binding(issue_number: int, body: dict) -> None:
    if type(issue_number) is not int or not 0 < issue_number < 2**63:
        raise ValueError('invalid issue number')
    if not isinstance(body, dict):
        raise ValueError('V1 body must be an object')
    body_number = body.get('issue_number')
    if type(body_number) is not int or body_number != issue_number:
        raise ValueError('body issue number does not match the envelope')


def encode_v1(issue_number: int, body: dict) -> bytes:
    _check_binding(issue_number, body)
    return _canonical({
        'version': V1_VERSION, 'issue_number': issue_number,
        'body': body, 'checksum': body_checksum(body),
    })


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def parse_v1(original: bytes) -> V1Envelope:
    if not isinstance(original, bytes):
        raise ValueError('packet must be bytes')
    try:
        envelope = json.loads(original.decode('utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(envelope, dict) or set(envelope) != {'version', 'issue_number', 'body', 'checksum'}:
            raise ValueError('invalid V1 envelope fields')
        version = envelope['version']
        if type(version) is not int or version != V1_VERSION:
            raise ValueError('unsupported packet version')
        issue_number, body, checksum = envelope['issue_number'], envelope['body'], envelope['checksum']
        _check_binding(issue_number, body)
        if not isinstance(checksum, str) or checksum != body_checksum(body):
            raise ValueError('body checksum mismatch')
    except RecursionError as error:
        raise ValueError('packet nesting is too deep') from error
    return V1Envelope(issue_number, body, checksum)
