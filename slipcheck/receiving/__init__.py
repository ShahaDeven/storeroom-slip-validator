"""Receiving: check a delivery receipt against its purchase order the moment it arrives.

The same pattern as the slip checker, on the other side of the storeroom door: a document
comes in (a PDF with a text layer, or an image read by a vision model), it is turned into
fields with provenance, and plain rules compare it with the system of record.
"""
