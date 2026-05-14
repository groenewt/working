-- Roll up catalog inventory by source class.
SELECT
  document_inventory.dir1 AS dir1,
  document_inventory.source_label AS source_label,
  document_inventory.file_kind AS file_kind,
  document_inventory.files AS files,
  document_inventory.bytes AS bytes,
  document_inventory.words AS words
FROM v_document_inventory AS document_inventory;
