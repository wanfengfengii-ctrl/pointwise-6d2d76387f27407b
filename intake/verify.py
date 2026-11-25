from dataclasses import dataclass

from issue.envelope import parse_v1


@dataclass(frozen=True)
class VerifiedPacket:
    issue_number: int
    checksum: str
    original: bytes


class PacketVerificationError(ValueError):
    pass


def verify_packet(original: bytes) -> VerifiedPacket:
    try:
        envelope = parse_v1(original)
    except ValueError as error:
        raise PacketVerificationError(str(error)) from error
    return VerifiedPacket(envelope.issue_number, envelope.checksum, original)
