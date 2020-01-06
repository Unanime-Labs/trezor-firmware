# Automatically generated by pb2py
# fmt: off
from .. import protobuf as p

if __debug__:
    try:
        from typing import Dict, List  # noqa: F401
        from typing_extensions import Literal  # noqa: F401
    except ImportError:
        pass


class OntologyWithdrawOng(p.MessageType):

    def __init__(
        self,
        amount: int = None,
        from_address: str = None,
        to_address: str = None,
    ) -> None:
        self.amount = amount
        self.from_address = from_address
        self.to_address = to_address

    @classmethod
    def get_fields(cls) -> Dict:
        return {
            1: ('amount', p.UVarintType, 0),
            2: ('from_address', p.UnicodeType, 0),
            3: ('to_address', p.UnicodeType, 0),
        }