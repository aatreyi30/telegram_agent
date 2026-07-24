"use client";

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import { cn } from "@/lib/utils";

const SIZE_CLASS: Record<"default" | "sm" | "lg", string> = {
  sm: "size-6",
  default: "size-8",
  lg: "size-10",
};

function Avatar({
  className,
  size = "default",
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Root> & {
  size?: "default" | "sm" | "lg";
}) {
  return (
    <AvatarPrimitive.Root
      className={cn(
        "relative flex shrink-0 select-none overflow-hidden rounded-full ring-1 ring-border",
        SIZE_CLASS[size],
        className,
      )}
      {...props}
    />
  );
}

function AvatarImage({ className, ...props }: React.ComponentProps<typeof AvatarPrimitive.Image>) {
  return (
    <AvatarPrimitive.Image
      className={cn("aspect-square size-full object-cover", className)}
      {...props}
    />
  );
}

function AvatarFallback({ className, ...props }: React.ComponentProps<typeof AvatarPrimitive.Fallback>) {
  return (
    <AvatarPrimitive.Fallback
      className={cn("flex size-full items-center justify-center rounded-full bg-muted text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Avatar, AvatarImage, AvatarFallback };
