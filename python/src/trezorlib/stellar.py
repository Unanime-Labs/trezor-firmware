# This file is part of the Trezor project.
#
# Copyright (C) 2012-2019 SatoshiLabs and contributors
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License version 3
# as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the License along with this library.
# If not, see <https://www.gnu.org/licenses/lgpl-3.0.html>.
from decimal import Decimal
from typing import Union

from . import exceptions, messages
from .tools import expect

try:
    from stellar_sdk import (
        AccountMerge,
        AllowTrust,
        Asset,
        BumpSequence,
        ChangeTrust,
        CreateAccount,
        CreatePassiveSellOffer,
        HashMemo,
        IdMemo,
        ManageData,
        ManageSellOffer,
        Operation,
        PathPaymentStrictReceive,
        Payment,
        ReturnHashMemo,
        SetOptions,
        TextMemo,
        TransactionEnvelope,
        TrustLineEntryFlag,
        Price,
        Network,
    )
    from stellar_sdk.xdr.signer_key_type import SignerKeyType

    HAVE_STELLAR_SDK = True
    DEFAULT_NETWORK_PASSPHRASE = Network.PUBLIC_NETWORK_PASSPHRASE

except ImportError:
    HAVE_STELLAR_SDK = False
    DEFAULT_NETWORK_PASSPHRASE = "Public Global Stellar Network ; September 2015"

# Memo types
MEMO_TYPE_NONE = 0
MEMO_TYPE_TEXT = 1
MEMO_TYPE_ID = 2
MEMO_TYPE_HASH = 3
MEMO_TYPE_RETURN = 4

# Asset types
ASSET_TYPE_NATIVE = 0
ASSET_TYPE_ALPHA4 = 1
ASSET_TYPE_ALPHA12 = 2

DEFAULT_BIP32_PATH = "m/44h/148h/0h"
# Stellar's BIP32 differs to Bitcoin's see https://github.com/stellar/stellar-protocol/blob/master/ecosystem/sep-0005.md


def from_envelope(envelope: "TransactionEnvelope"):
    """Parses transaction envelope into a map with the following keys:
    tx - a StellarSignTx describing the transaction header
    operations - an array of protobuf message objects for each operation
    """
    if not HAVE_STELLAR_SDK:
        raise RuntimeError("Stellar SDK not available")
    tx = messages.StellarSignTx()
    parsed_tx = envelope.transaction
    tx.source_account = parsed_tx.source.account_id
    tx.fee = parsed_tx.fee
    tx.sequence_number = parsed_tx.sequence

    # Timebounds is an optional field
    if parsed_tx.time_bounds:
        tx.timebounds_start = parsed_tx.time_bounds.min_time
        tx.timebounds_end = parsed_tx.time_bounds.max_time

    memo = parsed_tx.memo
    if isinstance(memo, TextMemo):
        # memo_text is specified as UTF-8 string, but returned as bytes from the XDR parser
        tx.memo_type = MEMO_TYPE_TEXT
        tx.memo_text = memo.memo_text.decode("utf-8")
    elif isinstance(memo, IdMemo):
        tx.memo_type = MEMO_TYPE_ID
        tx.memo_id = memo.memo_id
    elif isinstance(memo, HashMemo):
        tx.memo_type = MEMO_TYPE_HASH
        tx.memo_hash = memo.memo_hash
    elif isinstance(memo, ReturnHashMemo):
        tx.memo_type = MEMO_TYPE_RETURN
        tx.memo_hash = memo.memo_return
    else:
        tx.memo_type = MEMO_TYPE_NONE

    tx.num_operations = len(parsed_tx.operations)
    operations = [_read_operation(op) for op in parsed_tx.operations]
    return tx, operations


def _read_operation(op: "Operation"):
    # TODO: Let's add muxed account support later.
    if op.source:
        source_account = op.source.account_id
    else:
        source_account = None
    if isinstance(op, CreateAccount):
        return messages.StellarCreateAccountOp(
            source_account=source_account,
            new_account=op.destination,
            starting_balance=_read_amount(op.starting_balance),
        )
    if isinstance(op, Payment):
        return messages.StellarPaymentOp(
            source_account=source_account,
            destination_account=op.destination.account_id,
            asset=_read_asset(op.asset),
            amount=_read_amount(op.amount),
        )
    if isinstance(op, PathPaymentStrictReceive):
        operation = messages.StellarPathPaymentOp(
            source_account=source_account,
            send_asset=_read_asset(op.send_asset),
            send_max=_read_amount(op.send_max),
            destination_account=op.destination.account_id,
            destination_asset=_read_asset(op.dest_asset),
            destination_amount=_read_amount(op.dest_amount),
            paths=[_read_asset(asset) for asset in op.path],
        )
        return operation
    if isinstance(op, ManageSellOffer):
        price = _read_price(op.price)
        return messages.StellarManageOfferOp(
            source_account=source_account,
            selling_asset=_read_asset(op.selling),
            buying_asset=_read_asset(op.buying),
            amount=_read_amount(op.amount),
            price_n=price.n,
            price_d=price.d,
            offer_id=op.offer_id,
        )
    if isinstance(op, CreatePassiveSellOffer):
        price = _read_price(op.price)
        return messages.StellarCreatePassiveOfferOp(
            source_account=source_account,
            selling_asset=_read_asset(op.selling),
            buying_asset=_read_asset(op.buying),
            amount=_read_amount(op.amount),
            price_n=price.n,
            price_d=price.d,
        )
    if isinstance(op, SetOptions):
        operation = messages.StellarSetOptionsOp(
            source_account=source_account,
            inflation_destination_account=op.inflation_dest,
            clear_flags=op.clear_flags,
            set_flags=op.set_flags,
            master_weight=op.master_weight,
            low_threshold=op.low_threshold,
            medium_threshold=op.med_threshold,
            high_threshold=op.high_threshold,
            home_domain=op.home_domain,
        )
        if op.signer:
            signer_type = op.signer.signer_key.signer_key.type
            if signer_type == SignerKeyType.SIGNER_KEY_TYPE_ED25519:
                signer_key = op.signer.signer_key.signer_key.ed25519.uint256
            elif signer_type == SignerKeyType.SIGNER_KEY_TYPE_HASH_X:
                signer_key = op.signer.signer_key.signer_key.hash_x.uint256
            elif signer_type == SignerKeyType.SIGNER_KEY_TYPE_PRE_AUTH_TX:
                signer_key = op.signer.signer_key.signer_key.pre_auth_tx.uint256
            else:
                raise ValueError("Unsupported signer key type")
            operation.signer_type = signer_type.value
            operation.signer_key = signer_key
            operation.signer_weight = op.signer.weight
        return operation
    if isinstance(op, ChangeTrust):
        return messages.StellarChangeTrustOp(
            source_account=source_account,
            asset=_read_asset(op.asset),
            limit=_read_amount(op.limit),
        )
    if isinstance(op, AllowTrust):
        if op.authorize not in (
            TrustLineEntryFlag.UNAUTHORIZED_FLAG,
            TrustLineEntryFlag.AUTHORIZED_FLAG,
        ):
            raise ValueError("Unsupported trust line flag")
        asset_type = (
            ASSET_TYPE_ALPHA4 if len(op.asset_code) <= 4 else ASSET_TYPE_ALPHA12
        )
        return messages.StellarAllowTrustOp(
            source_account=source_account,
            trusted_account=op.trustor,
            asset_type=asset_type,
            asset_code=op.asset_code,
            is_authorized=op.authorize.value,
        )
    if isinstance(op, AccountMerge):
        return messages.StellarAccountMergeOp(
            source_account=source_account,
            destination_account=op.destination.account_id,
        )
    # Inflation is not implemented since anyone can submit this operation to the network
    if isinstance(op, ManageData):
        return messages.StellarManageDataOp(
            source_account=source_account,
            key=op.data_name,
            value=op.data_value,
        )
    if isinstance(op, BumpSequence):
        return messages.StellarBumpSequenceOp(
            source_account=source_account, bump_to=op.bump_to
        )
    raise ValueError(f"Unknown operation type: {op.__class__.__name__}")


def _read_amount(amount: str) -> int:
    return Operation.to_xdr_amount(amount)


def _read_price(price: Union["Price", str, Decimal]) -> "Price":
    # In the coming stellar-sdk 5.x, the type of price must be Price,
    # at that time we can remove this function
    if isinstance(price, Price):
        return price
    return Price.from_raw_price(price)


def _read_asset(asset: "Asset") -> messages.StellarAssetType:
    """Reads a stellar Asset from unpacker"""
    if asset.is_native():
        return messages.StellarAssetType(type=ASSET_TYPE_NATIVE)
    if asset.guess_asset_type() == "credit_alphanum4":
        return messages.StellarAssetType(
            type=ASSET_TYPE_ALPHA4, code=asset.code, issuer=asset.issuer
        )
    if asset.guess_asset_type() == "credit_alphanum12":
        return messages.StellarAssetType(
            type=ASSET_TYPE_ALPHA12, code=asset.code, issuer=asset.issuer
        )
    raise ValueError("Unsupported asset type")


# ====== Client functions ====== #


@expect(messages.StellarAddress, field="address")
def get_address(client, address_n, show_display=False):
    return client.call(
        messages.StellarGetAddress(address_n=address_n, show_display=show_display)
    )


def sign_tx(
    client, tx, operations, address_n, network_passphrase=DEFAULT_NETWORK_PASSPHRASE
):
    tx.network_passphrase = network_passphrase
    tx.address_n = address_n
    tx.num_operations = len(operations)
    # Signing loop works as follows:
    #
    # 1. Start with tx (header information for the transaction) and operations (an array of operation protobuf messagess)
    # 2. Send the tx header to the device
    # 3. Receive a StellarTxOpRequest message
    # 4. Send operations one by one until all operations have been sent. If there are more operations to sign, the device will send a StellarTxOpRequest message
    # 5. The final message received will be StellarSignedTx which is returned from this method
    resp = client.call(tx)
    try:
        while isinstance(resp, messages.StellarTxOpRequest):
            resp = client.call(operations.pop(0))
    except IndexError:
        # pop from empty list
        raise exceptions.TrezorException(
            "Reached end of operations without a signature."
        ) from None

    if not isinstance(resp, messages.StellarSignedTx):
        raise exceptions.TrezorException(
            "Unexpected message: {}".format(resp.__class__.__name__)
        )

    if operations:
        raise exceptions.TrezorException(
            "Received a signature before processing all operations."
        )

    return resp
