import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

// GPU-cheap animated backdrop: a dark base, a subtle accent radial glow, and a
// per-bucket line/grid pattern drawn with SVG strokes. No filter:blur (plan §8.1
// forbids it — it's the single most expensive CSS op for the headless renderer).
export const Background: React.FC<{ accent: string; pattern: string }> = ({
  accent,
  pattern,
}) => {
  const frame = useCurrentFrame();
  const drift = (frame % 300) / 300; // slow loop, no per-frame layout cost

  return (
    <AbsoluteFill style={{ backgroundColor: "#0B0F17" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(60% 40% at 50% ${20 + drift * 10}%, ${accent}33, transparent 70%)`,
        }}
      />
      <PatternLayer accent={accent} pattern={pattern} />
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(11,15,23,0) 55%, rgba(11,15,23,0.85) 100%)",
        }}
      />
    </AbsoluteFill>
  );
};

const PatternLayer: React.FC<{ accent: string; pattern: string }> = ({
  accent,
  pattern,
}) => {
  const stroke = `${accent}22`;
  if (pattern === "dots") {
    return (
      <svg width="100%" height="100%" style={{ position: "absolute" }}>
        <defs>
          <pattern id="p" width="64" height="64" patternUnits="userSpaceOnUse">
            <circle cx="6" cy="6" r="3" fill={stroke} />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#p)" />
      </svg>
    );
  }
  // default: grid / lines / contour all render as a stroked grid (cheap, on-brand)
  const vertical = pattern === "lines" || pattern === "lanes";
  return (
    <svg width="100%" height="100%" style={{ position: "absolute" }}>
      <defs>
        <pattern id="p" width="80" height="80" patternUnits="userSpaceOnUse">
          {!vertical && <path d="M0 0 H80" stroke={stroke} strokeWidth="2" />}
          <path d="M0 0 V80" stroke={stroke} strokeWidth="2" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#p)" />
    </svg>
  );
};
