import type { AlexaWiringStep } from "../contracts";
import { alexaCognitoClientStep } from "./cognito-client";

/**
 * Deploy-time wiring beyond the plugin's own (the Lambda permission, its settings and the endpoint output). A step is a file in
 * this folder (for example the Cognito app client for account linking); add one line here to run it. Steps run in this order.
 */
export const ALEXA_WIRING_STEPS: readonly AlexaWiringStep[] = [alexaCognitoClientStep];
