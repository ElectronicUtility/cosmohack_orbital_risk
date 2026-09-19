# UI rebuild, 19 September 2026

The rejected version was a presentation poster: a slogan, repeated all-caps labels, green-on-green panels, three large duplicate cards, several parallel window selectors, and a long single-page flow. The screenshot supplied by the user is the baseline. These are observations about this implementation, not proof of AI authorship.

## Research translated into decisions

- [Romero et al., 2026](https://arxiv.org/abs/2605.15124): 92 participants rated AI-generated and human prototypes without authorship labels. Functional quality and originality diverged. This supports evaluating specific workflows rather than treating visual fashion as an AI detector.
- [NN/g, AI Prototyping in Real Design Contexts](https://www.nngroup.com/articles/ai-prototyping/): generic patterns can emphasize the wrong content. Here the planning windows, their dates, and factor eligibility take precedence over slogans and decorative telemetry.
- [NN/g, Aesthetic and Minimalist Design](https://www.nngroup.com/articles/aesthetic-minimalist-design/): remove competing information while preserving task utility. Explanations belong in details, but dates, units, data age, and forecast/reconstruction distinctions stay discoverable.
- [NN/g, Complex Applications](https://www.nngroup.com/articles/complex-application-design/): disclose detail progressively and keep users oriented. Planning, saved calculations, sources, and methodology receive separate addressable views.
- [Carbon, Data tables](https://carbondesignsystem.com/components/data-table/usage/): use aligned rows for comparing structured values. Three equal windows become a single comparison table, not three repetitive cards.
- [NHS, Icons](https://service-manual.nhs.uk/design-system/styles/icons): familiar icon controls need accessible names; unclear actions retain visible labels. No unlabeled mystery navigation.
- [Linear, calmer interface](https://linear.app/now/behind-the-latest-design-refresh): navigation recedes and actions occupy predictable locations. This is a hierarchy reference, not a template to copy.

## Design plan before implementation

Palette: white #ffffff, canvas gray #f4f6f8, ink #202a37, secondary #667180, control blue #245ac5, spacecraft orange #c96a2b. Amber/red reserved for actual attention/error states. No full-screen tint, neon, ornamental gradient, or repeated colored borders.

Type: Segoe UI on Windows with system fallbacks; 28px page heading, 16px section heading, 14px body, 12px metadata. Tabular numerals for measurements, no general monospace or tracked uppercase labels.

Layout: quiet 196px sidebar, 60px utility header, compact page title; orbit view beside a single table of windows, with time controls attached to the visualization. Calculation parameters live in a focused dialog. Archive is a searchable list, sources an expandable provenance table, methodology a short reference page.

```
Navigation | Page / station                  report / new calculation
           | Date + selected saved scenario
           | Orbit diagram      | A  start/end  shadow
           |                    | B  start/end  shadow
           | playback           | C  start/end  shadow
           | Time-aligned conditions, details on request
```

Critique of plan: white + blue alone would be another generic SaaS shell. The product-specific element is the linked orbital geometry and window scheduling, not a dashboard card kit. Keep one window selector, integrate measurable shadow intervals, and use actual source records throughout. Do not add fake collaboration, notifications, integrations, live status, maps, or metrics to imply a larger product.

Success checks: direct routes and browser history work; selecting a row updates orbit and timeline; new calculations preserve previous results on error; archived examples never read as live data; source detail and report export remain available; mobile and keyboard navigation work.
