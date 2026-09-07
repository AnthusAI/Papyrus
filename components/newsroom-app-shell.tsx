import type { ReactNode } from "react";
import { cn } from "../lib/utils";

type NewsroomAppShellProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  drawer?: ReactNode;
  headerTrailing?: ReactNode;
  labelledBy: string;
  navigation?: ReactNode;
  showNavigation?: boolean;
  title: ReactNode;
};

export function NewsroomAppShell({
  children,
  className,
  contentClassName,
  drawer,
  headerTrailing,
  labelledBy,
  navigation,
  showNavigation = true,
  title,
}: NewsroomAppShellProps) {
  return (
    <div className={cn("newsroom-app-shell__frame", className)}>
      <header className="newsroom-app-shell__header">
        <div className="newsroom-app-shell__title-block">
          <p className="newsroom-app-shell__eyebrow">Ops desk</p>
          <h1 className="newsroom-app-shell__title" id={labelledBy}>
            {title}
          </h1>
        </div>
        {headerTrailing ? (
          <div className="newsroom-app-shell__meta" aria-label="Newsroom session">
            {headerTrailing}
          </div>
        ) : null}
      </header>
      <div className="newsroom-app-shell__body">
        {showNavigation && navigation ? (
          <nav className="newsroom-app-shell__nav news-desk-tabs" aria-label="Newsroom sections">
            {navigation}
          </nav>
        ) : null}
        {drawer}
        <div className={cn("newsroom-app-shell__content news-desk-page", contentClassName)}>
          {children}
        </div>
      </div>
    </div>
  );
}
