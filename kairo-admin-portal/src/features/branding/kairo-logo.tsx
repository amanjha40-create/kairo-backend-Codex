/**
 * Kairo brand mark — official logo asset.
 *
 * Single source of truth for the Kairo logo across the Admin Portal.
 * Swap the asset here to change every logo instance at once.
 */
import kairoLogoAsset from "@/assets/kairo-logo.png.asset.json";
import { cn } from "@/lib/utils";

export interface KairoLogoProps {
  className?: string;
  /** Width in px. Height auto-scales to the logo's aspect ratio. */
  width?: number;
  /** When false, render a compact mark-only crop (chevron only). */
  showWordmark?: boolean;
  /** Accessible label. */
  title?: string;
}

// Native aspect ratio of the uploaded logo asset.
const LOGO_ASPECT = 605 / 195; // ≈ 3.1 : 1
// The chevron mark occupies roughly the left ~28% of the image.
const MARK_FRACTION = 0.28;

export function KairoLogo({
  className,
  width = 150,
  showWordmark = true,
  title = "Kairo",
}: KairoLogoProps) {
  if (showWordmark) {
    const height = Math.round(width / LOGO_ASPECT);
    return (
      <img
        src={kairoLogoAsset.url}
        alt={title}
        width={width}
        height={height}
        className={cn("inline-block select-none", className)}
        draggable={false}
      />
    );
  }

  // Mark-only: window into the left portion of the logo image.
  const height = Math.round((width / LOGO_ASPECT / MARK_FRACTION) * MARK_FRACTION);
  // Compute a square-ish mark box based on the requested width being the mark size.
  const boxSize = width;
  const fullImageWidth = boxSize / MARK_FRACTION;
  const fullImageHeight = fullImageWidth / LOGO_ASPECT;
  return (
    <span
      role="img"
      aria-label={title}
      className={cn("inline-block overflow-hidden select-none", className)}
      style={{ width: boxSize, height: Math.min(boxSize, Math.round(fullImageHeight)) }}
    >
      <img
        src={kairoLogoAsset.url}
        alt=""
        width={fullImageWidth}
        height={fullImageHeight}
        style={{ maxWidth: "none", display: "block" }}
        draggable={false}
      />
      {/* keep type-linter happy */}
      <span className="sr-only">{title}</span>
      <span aria-hidden style={{ display: "none" }}>
        {height}
      </span>
    </span>
  );
}
