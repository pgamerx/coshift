import { Composition } from "remotion";
import { Coshift } from "./Coshift";

export const Root = () => (
  <Composition id="Coshift" component={Coshift} durationInFrames={690} fps={30} width={960} height={540} />
);
