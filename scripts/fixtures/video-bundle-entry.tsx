import React from "react";

type FixtureSlideProps = { title?: string };

function FixtureSlide({ title = "" }: FixtureSlideProps) {
  return <h1>{title}</h1>;
}

const videoApi = (window as unknown as {
  Babulus?: { registerComponent: (name: string, component: React.ComponentType<FixtureSlideProps>) => void };
}).Babulus;
if (!videoApi?.registerComponent) {
  throw new Error("The standard VideoML entry did not provide window.Babulus.registerComponent.");
}
videoApi.registerComponent("FixtureSlide", FixtureSlide);
