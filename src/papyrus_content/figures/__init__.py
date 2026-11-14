"""Figures: diagrams, charts and illustrations drawn from one SVG source and rendered to a light and a dark PNG.

The general rules (``data/figures/rules.md``), the shape library (``data/figures/primitives.svg``), the checks and the renderer live here.
Everything that belongs to one site (color and type tokens, fonts, the role mapping, worked examples) is a *design system*, read through
``design_system.DesignSystemSource``. Today the only source is a directory; a site's backend data will be another source behind the same
three methods, so nothing else changes. ``papyrus figures --help`` lists the commands.
"""
