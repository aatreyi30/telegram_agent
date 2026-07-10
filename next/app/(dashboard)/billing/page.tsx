"use client";

import { useState } from "react";
import { HugeiconsIcon } from "@hugeicons/react";
import { CheckmarkCircle01Icon, CreditCardIcon } from "@hugeicons/core-free-icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const plans = [
  {
    name: "Starter",
    monthlyPrice: 0,
    annualPrice: 0,
    description: "For small channels",
    features: ["1 channel", "Basic analytics", "7-day data history", "Up to 500 posts/mo"],
    popular: false,
  },
  {
    name: "Growth",
    monthlyPrice: 29,
    annualPrice: 23,
    description: "For growing creators",
    features: [
      "5 channels",
      "Advanced analytics + AI insights",
      "90-day data history",
      "Competitor tracking (up to 10)",
      "AI draft generation",
      "Priority support",
    ],
    popular: true,
  },
  {
    name: "Enterprise",
    monthlyPrice: 99,
    annualPrice: 79,
    description: "For teams & agencies",
    features: [
      "Unlimited channels",
      "Full data history",
      "All competitors",
      "Custom AI blueprint",
      "Dedicated support",
      "White-label exports",
    ],
    popular: false,
  },
];

const sharedFeatures = [
  "AES-256 encrypted data",
  "REST API access",
  "Community support forum",
  "99.9% uptime SLA",
  "SOC 2 compliant",
];

export default function BillingPage() {
  const [annual, setAnnual] = useState(false);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Billing &amp; plan</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground mt-1.5">
          <HugeiconsIcon icon={CreditCardIcon} className="h-3.5 w-3.5 shrink-0" />
          Manage your subscription and choose the plan that fits your needs.
        </p>
      </div>

      <div className="flex items-center justify-center gap-3">
        <button
          onClick={() => setAnnual(false)}
          className={cn(
            "text-sm font-medium transition-colors",
            !annual ? "text-foreground" : "text-muted-foreground"
          )}
        >
          Monthly
        </button>
        <button
          onClick={() => setAnnual(true)}
          className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <span
            className={cn(
              "pointer-events-none block h-5 w-5 rounded-full bg-background shadow-lg ring-0 transition-transform",
              annual ? "translate-x-5" : "translate-x-0"
            )}
          />
        </button>
        <button
          onClick={() => setAnnual(true)}
          className={cn(
            "inline-flex items-center gap-1.5 text-sm font-medium transition-colors",
            annual ? "text-foreground" : "text-muted-foreground"
          )}
        >
          Annual
          {annual && (
            <Badge variant="success" className="text-[10px] px-1.5 py-0">
              Save 20%
            </Badge>
          )}
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-3 items-start">
        {plans.map((plan) => {
          const price = annual ? plan.annualPrice : plan.monthlyPrice;
          const period = annual ? "/mo, billed annually" : "/mo";

          return (
            <Card
              key={plan.name}
              className={cn(
                "relative flex flex-col rounded-xl",
                plan.popular && "border-primary shadow-md"
              )}
            >
              {plan.popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <Badge variant="primary">Most Popular</Badge>
                </div>
              )}
              <CardHeader className={cn(plan.popular && "pt-8")}>
                <CardTitle>{plan.name}</CardTitle>
                <CardDescription>{plan.description}</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 space-y-6">
                <div>
                  <span className="text-4xl font-bold">
                    ${price}
                  </span>
                  <span className="ml-1 text-sm text-muted-foreground">{period}</span>
                </div>
                <ul className="space-y-3">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-sm">
                      <HugeiconsIcon icon={CheckmarkCircle01Icon} className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
              <CardFooter>
                <Button
                  className="w-full"
                  variant={plan.popular ? "default" : "outline"}
                >
                  {plan.name === "Starter" ? "Current plan" : "Get started"}
                </Button>
              </CardFooter>
            </Card>
          );
        })}
      </div>

      <Card className="rounded-xl">
        <CardHeader>
          <CardTitle className="text-base">All plans include</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-6">
            {sharedFeatures.map((feature) => (
              <div key={feature} className="flex items-center gap-2 text-sm text-muted-foreground">
                <HugeiconsIcon icon={CheckmarkCircle01Icon} className="h-4 w-4 text-primary" />
                {feature}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
