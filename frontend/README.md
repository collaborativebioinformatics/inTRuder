# Frontend (`frontend/`)

Next.js (App Router) + Tailwind CSS v4 + [assistant-ui](https://www.assistant-ui.com).

## Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local     # points at the backend, default localhost:8000
npm run dev
```

Open <http://localhost:3000>. The backend must be running — see `../backend/README.md`.

## The idea

One visual primitive, three zoom levels.

An inserted allele is drawn as a **strip of motif blocks**, not as bases. A block
is one repeat array; its width is how much sequence it accounts for; grey is
non-repetitive flank. Base-level rendering fails on tandem repeats — a GCC and a
CGG expansion are the same colored mush — so the encoding moves up a level to
where the information actually is.

| Level | What it shows | Color carries | Width scale |
|---|---|---|---|
| Catalog | Every locus, one strip each | Novel vs catalogued | sqrt-compressed per row |
| Locus | One locus, every carrier | Motif identity | Shared linear |
| Allele | One strip, hovered | Motif identity | Shared linear |

Novelty owns the color channel at level 1 so the novel fraction reads as texture
before anyone touches a control. At level 2 novelty is constant, so the channel
goes back to motif identity.

The width scales differ deliberately. Level 1 compares *across* loci whose lengths
span two orders of magnitude, so a shared linear scale would render most rows as a
1px sliver — each row's overall width is sqrt-compressed while segments within it
stay strictly linear. Level 2 compares *within* one locus, where the range is
narrow and comparing allele lengths between samples is the entire point.

## Chat drives the view

`components/Chat.tsx` and `components/FilterBar.tsx` both write to one
`ViewFilters` object in `lib/viewStore.tsx`, and the backend's `set_view` tool
takes exactly that shape. So a question typed into chat moves the same view a
click would, and chips the agent touched are outlined to show what changed.

That is the point of the chat pane. It is not a sidebar bolted onto a dashboard —
it is a second way to edit the same state.

## Color

Chart colors come from a validated palette defined as CSS custom properties in
`app/globals.css`, with light on bare `:root` and dark under both the OS media
query and an explicit `[data-theme="dark"]` stamp.

Motifs use **three** categorical slots, not eight. In a barcode any two blocks can
end up adjacent, so the palette has to clear all-pairs colorblind separation
rather than the easier adjacent-pairs case, and only the first three slots do.
Motifs past the top three at a locus fold into a neutral "other" — which is also
how the data behaves, since loci are dominated by one or two motifs.

## Layout

| Path | Role |
|---|---|
| `app/page.tsx` | Three-column shell, data fetching |
| `app/globals.css` | Design tokens, light/dark |
| `components/MotifBarcode.tsx` | The core primitive |
| `components/CatalogView.tsx` | Level 1 |
| `components/LocusView.tsx` | Levels 2–3 |
| `components/Funnel.tsx` | Discovery funnel, clickable to filter |
| `components/FilterBar.tsx` | Filter chips |
| `components/SearchBox.tsx` | One box for a genomic range or a gene name |
| `components/Chat.tsx` | assistant-ui thread + SSE adapter |
| `lib/viewStore.tsx` | The shared view state |
| `lib/api.ts` | Backend client, SSE parser |
| `lib/palette.ts` | Motif→color assignment |
| `lib/region.ts` | Reads `chr3:1,000-50,000`, and tells a range from a gene |

## Checks

```bash
npx tsc --noEmit
npm run build
```
