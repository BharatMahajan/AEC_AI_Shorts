import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useVideoConfig } from "remotion";
import { ShortProps } from "./schema";
import { Background } from "./theme/Background";
import { Captions } from "./components/Captions";
import { ProgressBar } from "./components/ProgressBar";
import { Hook } from "./scenes/Hook";
import { FeatureCards } from "./scenes/FeatureCards";
import { Workflow } from "./scenes/Workflow";
import { CTA } from "./scenes/CTA";

// Scene timeline as fractions of the (audio-derived) total length:
//   Hook 0-20% | Feature Cards 20-55% | Workflow 55-82% | CTA 82-100%
// Captions + progress bar are always on, layered above the scenes.
export const Short: React.FC<ShortProps> = (props) => {
  const { durationInFrames } = useVideoConfig();
  const f = (frac: number) => Math.round(durationInFrames * frac);
  const contentBottomInset = 460;

  const hookEnd = f(0.2);
  const cardsEnd = f(0.55);
  const flowEnd = f(0.82);

  return (
    <AbsoluteFill>
      <Background accent={props.accent} pattern={props.pattern} />

      <Sequence from={0} durationInFrames={hookEnd}>
        <Hook
          hook={props.hook}
          title={props.title}
          accent={props.accent}
          contentBottomInset={contentBottomInset}
        />
      </Sequence>

      <Sequence from={hookEnd} durationInFrames={cardsEnd - hookEnd}>
        <FeatureCards
          points={props.points}
          accent={props.accent}
          contentBottomInset={contentBottomInset}
        />
      </Sequence>

      <Sequence from={cardsEnd} durationInFrames={flowEnd - cardsEnd}>
        <Workflow
          flow={props.flow}
          accent={props.accent}
          contentBottomInset={contentBottomInset}
        />
      </Sequence>

      <Sequence from={flowEnd} durationInFrames={durationInFrames - flowEnd}>
        <CTA cta={props.cta} accent={props.accent} contentBottomInset={contentBottomInset} />
      </Sequence>

      <Captions captions={props.captions} accent={props.accent} />
      <ProgressBar accent={props.accent} />

      <Audio src={staticFile(props.audioSrc)} />
    </AbsoluteFill>
  );
};
