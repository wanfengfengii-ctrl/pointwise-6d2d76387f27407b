from intake.repository import AcceptedPacket
from intake.verify import VerifiedPacket


class PacketConflict(ValueError):
    pass


def resolve_reception(packet: VerifiedPacket, existing: AcceptedPacket | None) -> int | None:
    if existing is None:
        return None
    if existing.checksum != packet.checksum:
        raise PacketConflict(f'issue {packet.issue_number} was received with different content')
    return existing.receipt_id
