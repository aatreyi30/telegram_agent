import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, Bot, CalendarClock, Sparkles, Target, Users2 } from "lucide-react";
import { Logo, LogoMark } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuth } from "@/providers/auth";

const FEATURES = [
  { icon: Sparkles, title: "Strategy-compliant posts", desc: "Drafts that follow your learned strategy — right post types, right emojis, real affiliate links." },
  { icon: BarChart3, title: "Honest analytics", desc: "Views by day, hour, post-type and merchant — every number labeled with its time window and sample." },
  { icon: Bot, title: "Agentic pipeline", desc: "One click runs normalize → classify → intel → learn → growth → reason → plan → AI briefing." },
  { icon: Target, title: "Explainable insights", desc: "Every recommendation shows the calculation, the evidence, and the confidence behind it." },
  { icon: Users2, title: "Competitor intel", desc: "Cadence, timing and content-mix vs the most similar competitors — cross-checked against your own data." },
  { icon: CalendarClock, title: "Schedule & automate", desc: "Queue drafts into your best posting windows; sends stay gated until you're an admin." },
];

export function Landing() {
  const { user } = useAuth();
  const cta = user ? "/app" : "/login";

  return (
    <div className="min-h-screen bg-background">
      <header className="mx-auto flex max-w-6xl items-center justify-between p-5">
        <Logo />
        <Link to={cta}>
          <Button variant="outline">{user ? "Open dashboard" : "Log in"}</Button>
        </Link>
      </header>

      <section className="mx-auto max-w-6xl px-5 pb-16 pt-12 text-center">
        <div className="mx-auto mb-6 grid h-16 w-16 place-items-center">
          <LogoMark size={64} />
        </div>
        <h1 className="mx-auto max-w-3xl text-4xl font-extrabold tracking-tight md:text-5xl">
          Grow your Telegram deal channel on <span className="text-primary">evidence</span>, not guesswork.
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-lg text-muted-foreground">
          DealWing learns from your channel and your competitors, then writes strategy-compliant
          posts and tells you exactly what to do next — with the numbers to back it up.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link to={cta}>
            <Button size="lg">
              {user ? "Open dashboard" : "Get started"} <ArrowRight size={18} />
            </Button>
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 pb-24">
        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map((f) => (
            <Card key={f.title} className="p-6">
              <f.icon className="mb-3 text-primary" size={24} />
              <h3 className="font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{f.desc}</p>
            </Card>
          ))}
        </div>
      </section>

      <footer className="border-t py-8 text-center text-sm text-muted-foreground">
        DealWing — Telegram Growth OS
      </footer>
    </div>
  );
}
