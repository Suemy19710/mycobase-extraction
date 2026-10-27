"""mycobase-extraction: extract species descriptions from taxonomic PDFs into MycoBase.

Steps implemented here:
  1. layout   - read a PDF with its fonts, rebuild reading order, remove page clutter
  2. segment  - find where each species section starts and ends; resolve its name against
                the accepted list (Visagie et al. 2025) and MycoBank
Later steps (field extraction, value parsing, validation, merge) build on these.
"""
__version__ = "0.6.0"
