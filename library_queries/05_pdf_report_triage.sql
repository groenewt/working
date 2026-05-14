-- PDF report triage surface.
SELECT
  pdf_report_triage.doc_id AS doc_id,
  pdf_report_triage.rel_path AS rel_path,
  pdf_report_triage.title AS title,
  pdf_report_triage.pdf_pages AS pdf_pages,
  pdf_report_triage.word_count AS word_count,
  pdf_report_triage.topics AS topics,
  pdf_report_triage.flags AS flags
FROM v_agent_batch_pdf_report_triage AS pdf_report_triage;
