import { useTheme } from "./useTheme";
import { ProductWordmark } from "./marks/ProductWordmark";

// Shipped wordmark. Not an institutional mark — it names the product, not an
// operator — so it is a safe default for a self-hosted instance. Rendered
// inline rather than from /images, so its two tones follow the theme's brand
// ramp instead of staying the colours it was drawn in.
const DEFAULT_ALT = "Transferts";

export type ProductLogoProps = {
  /** Fallback height, used unless the theme states one. */
  height?: number;
  className?: string;
};

/**
 * The header logo: the operator's if the theme carries one (``header.icon``,
 * the key ``docs`` already uses), the product's wordmark otherwise.
 */
export function ProductLogo({ height = 40, className }: ProductLogoProps) {
  const icon = useTheme().header?.icon;

  // No image in the theme: our own mark, which the brand ramp recolours.
  if (!icon?.src) {
    return (
      <ProductWordmark
        className={className}
        height={icon?.height ?? height}
        title={icon?.alt ?? DEFAULT_ALT}
      />
    );
  }

  return (
    <img
      className={className}
      src={icon.src}
      // An operator may deliberately set "" to make the image decorative,
      // which is why this tests for undefined rather than falsiness.
      alt={icon.alt ?? DEFAULT_ALT}
      height={icon.height ?? height}
      width={icon.width}
      style={icon.style}
    />
  );
}
