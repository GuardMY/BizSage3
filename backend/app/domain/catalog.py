"""Industry reference data for BizSage3.

After removing hardcoded industry matching, this module is kept as a
placeholder for future domain-specific reference data (e.g. KPI benchmarks
per industry sub-category). Industry detection is now fully delegated to
the LLM via scene_recognize.
"""

# Industry detection is now LLM-driven — no hardcoded list.
# The scene_recognize node extracts the industry category from user messages
# dynamically, allowing it to adapt to granular sub-categories (e.g. 火锅、
# 茶饮、快餐) rather than being constrained to a fixed enum.
