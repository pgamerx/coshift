import { Composition } from "remotion";
import { Coshift } from "./Coshift";
import { HowItWorks, TypicalDay } from "./Diagrams";

export const Root = () => (
  <>
    <Composition id="Coshift" component={Coshift} durationInFrames={690} fps={30} width={960} height={540} />
    <Composition id="HowItWorks" component={HowItWorks} durationInFrames={1} fps={30} width={1210} height={520} />
    <Composition id="TypicalDay" component={TypicalDay} durationInFrames={1} fps={30} width={1210} height={640} />
  </>
);
