"""An address proof remains private even after replacement or address-version edits."""

from sqlalchemy import exists, or_

from app.models.permanent_address import (
    PermanentAddressDocument,
    PermanentAddressReview,
    PermanentAddressVersion,
)


def private_address_document(document_id):
    return or_(
        exists().where(PermanentAddressDocument.document_id == document_id),
        exists().where(PermanentAddressVersion.document_id == document_id),
        exists().where(PermanentAddressReview.document_id == document_id),
    )
