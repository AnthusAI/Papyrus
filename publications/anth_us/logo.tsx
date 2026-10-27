/**
 * The Anthus wordmark exactly as the live site header draws it (anth.us, `.site-brand__svg`): a pink tile
 * holding a pixel "A" followed by the pixel lettering. The paths are the site's own; the colors follow the
 * site's logo tokens so the newsroom CMS and the website show the same mark.
 */
function TileAndA() {
  return (
    <>
      <rect className="anth-us-logo-tile" height="900" width="712.5" x="-71.25" y="-75" />
      <path className="anth-us-logo-a" d="M142.5 0h285v75h-285zM71.25 75h142.5v75h-142.5zM356.25 75h142.5v75h-142.5zM71.25 150h142.5v75h-142.5zM356.25 150h142.5v75h-142.5zM0 225h142.5v75h-142.5zM427.5 225h142.5v75h-142.5zM0 300h142.5v75h-142.5zM427.5 300h142.5v75h-142.5zM0 375h570v75h-570zM0 450h570v75h-570zM0 525h142.5v75h-142.5zM427.5 525h142.5v75h-142.5zM0 600h142.5v75h-142.5zM427.5 600h142.5v75h-142.5zM0 675h142.5v75h-142.5zM427.5 675h142.5v75h-142.5z" />
    </>
  );
}

export function AnthUsLogo({ className }: { className?: string }) {
  return (
    <svg aria-label="Anthus" className={className} role="img" shapeRendering="crispEdges" viewBox="-71.25 -75 10486.8 900">
      <TileAndA />
      <path className="anth-us-logo-word" d="M1159 450V0H1309V750H1129V720H1099V660H1069V600H1039V540H1009V480H979V420H949V360H919V300H889V750H739V0H919V30H949V90H979V150H1009V210H1039V270H1069V330H1099V390H1129V450ZM1928 0V150H1778V750H1628V150H1478V0ZM2457 300V0H2607V750H2457V450H2247V750H2097V0H2247V300ZM2956 570V600H3106V570H3136V0H3286V630H3256V690H3226V720H3166V750H2896V720H2836V690H2806V630H2776V0H2926V570ZM3635 570V600H3785V570H3815V480H3785V450H3575V420H3515V390H3485V330H3455V120H3485V60H3515V30H3575V0H3845V30H3905V60H3935V120H3965V210H3815V180H3785V150H3635V180H3605V270H3635V300H3845V330H3905V360H3935V420H3965V630H3935V690H3905V720H3845V750H3575V720H3515V690H3485V630H3455V510H3605V570Z" />
    </svg>
  );
}

/** The pink tile and pixel "A" alone: the newsroom's mobile top bar has no room for the full lettering. */
export function AnthUsLogoCompact({ className }: { className?: string }) {
  return (
    <svg aria-label="Anthus" className={className} role="img" shapeRendering="crispEdges" viewBox="-71.25 -75 712.5 900">
      <TileAndA />
    </svg>
  );
}
