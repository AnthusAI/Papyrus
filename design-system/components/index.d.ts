// Papyrus shared primitives. Documentation types: the bundle is plain JS.

/** Visual weight of an action. `default` is the one high-emphasis action per view. */
export type ButtonVariant =
  | "default"
  | "outline"
  | "secondary"
  | "ghost"
  | "destructive"
  | "link";

/** Control height, from the `control-*` tokens. */
export type ButtonSize = "xs" | "sm" | "default" | "lg";

export interface ButtonProps {
  variant?: ButtonVariant;
  /** `default` is 32px. Use `lg` for the primary page action, `xs` in dense tables. */
  size?: ButtonSize;
  type?: "button" | "submit" | "reset";
  disabled?: boolean;
  onClick?: (event: unknown) => void;
  className?: string;
  children?: unknown;
}

/** Which uppercase furniture style the label uses. */
export type EyebrowRole = "kicker" | "section" | "byline" | "meta";

export interface EyebrowProps {
  /** Element to render. Default `span`; use `h2` for a real section heading. */
  as?: string;
  role?: EyebrowRole;
  /** `alarm` paints the label in `danger-text`; reserve it for a live alarm state. */
  tone?: "default" | "alarm";
  className?: string;
  children?: unknown;
}

/** Which register the surface belongs to. */
export type PanelRegister = "paper" | "chrome" | "quiet" | "lifted";

export interface PanelProps {
  as?: string;
  /** `paper` is reader-facing: square, serif, a section rule on top. */
  register?: PanelRegister;
  pad?: "tight" | "default" | "loose";
  /** Renders a panel title in the register's own face. */
  title?: unknown;
  className?: string;
  children?: unknown;
}

export interface RuleProps {
  orientation?: "horizontal" | "vertical";
  /** `hairline` (1px) for columns and decks, `section` (2px) for section breaks. */
  weight?: "hairline" | "section";
  /** Draws the rule at `opacity-rule-soft`, for deck and inset rules. */
  soft?: boolean;
  /** An uppercase section label set before the rule. */
  label?: string;
  className?: string;
}

export declare function Button(props: ButtonProps): unknown;
export declare function Eyebrow(props: EyebrowProps): unknown;
export declare function Panel(props: PanelProps): unknown;
export declare function Rule(props: RuleProps): unknown;
