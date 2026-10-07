"""Source archive publication retains the destination it actually inspected."""
from .move_transaction import PathSwapTransaction, unique_staging_path
from .transaction_identity import path_receipt


def publish_release_archive(staged, destination, *, destination_receipt):
    transaction = PathSwapTransaction(staged, destination, unique_staging_path(destination),
        staging_path=staged, preserve_staging_on_rollback=True,
        replace_existing_destination=destination_receipt is not None,
        expected_destination_receipt=destination_receipt, expected_staging_receipt=path_receipt(staged))
    transaction.commit()
    transaction.discard_backup()
