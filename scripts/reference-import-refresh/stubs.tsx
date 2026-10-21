import React from "react";
export const usePathname = () => "/newsroom/references";
export const useRouter = () => ({ push: () => {}, replace: () => {}, refresh: () => {} });
export default function Link({ href, children, ...props }: React.ComponentProps<"a">) { return <a href={href} {...props}>{children}</a>; }
export const useOptionalNewsDeskClient = () => null;
export const loadReferenceAttachmentsForLineageId = async () => [];
export const loadStoragePathUrl = async () => { throw new Error("storage disconnected"); };
