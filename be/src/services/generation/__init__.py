"""Deal Enrichment + Post Generation (Phase 9).

Pipeline (source_truth/04 + source_truth/06):
  raw deal -> Deal Enrichment Engine -> Ranking -> Selection -> Formatting -> Publishing

Enrichment, ranking, selection, and formatting are fully built. Publishing and
affiliate-link injection depend on deferred integrations (GrabOn shortener/
affiliate + channel admin rights) and are scaffolded with explicit gates — never
faked.
"""
