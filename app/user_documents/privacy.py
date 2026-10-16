"""Read-time minimization for Aadhaar metadata, including pre-existing rows."""


def display_filename(document):
    if getattr(document, "document_type", None) == "aadhaar":
        return "aadhaar-document"
    return document.original_filename
