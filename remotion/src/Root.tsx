import React from "react";
import { Composition } from "remotion";
import { Short } from "./Short";
import { ShortPropsSchema, defaultProps } from "./schema";

// The composition's duration/size are driven by the incoming props
// (durationInFrames comes from the real audio length measured in L3), so a
// single composition adapts to every script with no hardcoded length.
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Short"
      component={Short}
      schema={ShortPropsSchema}
      defaultProps={defaultProps}
      durationInFrames={defaultProps.durationInFrames}
      fps={defaultProps.fps}
      width={defaultProps.width}
      height={defaultProps.height}
      calculateMetadata={({ props }) => ({
        durationInFrames: props.durationInFrames,
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
