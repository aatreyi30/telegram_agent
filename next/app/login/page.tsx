"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/auth";
import { api } from "@/services/api";
import { HugeiconsIcon } from "@hugeicons/react";
import { Sent02Icon } from "@hugeicons/core-free-icons";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [tab, setTab] = useState("signin");

  // Sign in state
  const [signinEmail, setSigninEmail] = useState("");
  const [signinPassword, setSigninPassword] = useState("");
  const [signinError, setSigninError] = useState("");
  const [signinLoading, setSigninLoading] = useState(false);

  // Sign up state
  const [signupName, setSignupName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [signupConfirm, setSignupConfirm] = useState("");
  const [signupError, setSignupError] = useState("");
  const [signupLoading, setSignupLoading] = useState(false);
  const [signupSuccess, setSignupSuccess] = useState(false);

  async function handleSignin(e: FormEvent) {
    e.preventDefault();
    setSigninError("");
    setSigninLoading(true);
    try {
      await login(signinEmail, signinPassword);
      router.push("/");
    } catch {
      setSigninError("Invalid email or password. Please try again.");
    } finally {
      setSigninLoading(false);
    }
  }

  async function handleSignup(e: FormEvent) {
    e.preventDefault();
    setSignupError("");
    setSignupLoading(true);
    try {
      if (signupPassword !== signupConfirm) {
        setSignupError("Passwords do not match.");
        return;
      }
      await api.post("/auth/register", {
        name: signupName,
        email: signupEmail,
        password: signupPassword,
      });
      setSignupSuccess(true);
      setTab("signin");
    } catch {
      setSignupError("Registration failed. Please try again.");
    } finally {
      setSignupLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="relative w-full max-w-sm overflow-hidden border-t-4 border-t-emerald-500 shadow-xl">
        <CardHeader className="space-y-1 pb-4 text-center">
          <div className="mb-2 flex justify-center">
            <div className="flex size-10 items-center justify-center rounded-lg bg-emerald-500">
              <HugeiconsIcon icon={Sent02Icon} size={20} className="-rotate-45 text-white" />
            </div>
          </div>
          <CardTitle className="text-xl">Welcome to DealWing</CardTitle>
          <CardDescription>Sign in to your account or create a new one</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="mb-6 w-full">
              <TabsTrigger value="signin" className="flex-1">
                Sign in
              </TabsTrigger>
              <TabsTrigger value="signup" className="flex-1">
                Sign up
              </TabsTrigger>
            </TabsList>

            <TabsContent value="signin">
              <form onSubmit={handleSignin} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="signin-email">Email</Label>
                  <Input
                    id="signin-email"
                    type="email"
                    placeholder="you@example.com"
                    value={signinEmail}
                    onChange={(e) => setSigninEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="signin-password">Password</Label>
                  <Input
                    id="signin-password"
                    type="password"
                    placeholder="••••••••"
                    value={signinPassword}
                    onChange={(e) => setSigninPassword(e.target.value)}
                    required
                  />
                </div>
                {signinError && <p className="text-sm text-destructive">{signinError}</p>}
                <Button type="submit" className="w-full" disabled={signinLoading}>
                  {signinLoading ? "Signing in..." : "Sign in"}
                </Button>
              </form>
            </TabsContent>

            <TabsContent value="signup">
              {signupSuccess ? (
                <div className="space-y-4 text-center">
                  <p className="text-sm text-emerald-600">
                    Account created successfully! Switch to the Sign in tab to log in.
                  </p>
                  <Button className="w-full" onClick={() => setTab("signin")}>
                    Go to Sign in
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleSignup} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="signup-name">Name</Label>
                    <Input
                      id="signup-name"
                      type="text"
                      placeholder="Your name"
                      value={signupName}
                      onChange={(e) => setSignupName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="signup-email">Email</Label>
                    <Input
                      id="signup-email"
                      type="email"
                      placeholder="you@example.com"
                      value={signupEmail}
                      onChange={(e) => setSignupEmail(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="signup-password">Password</Label>
                    <Input
                      id="signup-password"
                      type="password"
                      placeholder="••••••••"
                      value={signupPassword}
                      onChange={(e) => setSignupPassword(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="signup-confirm">Confirm password</Label>
                    <Input
                      id="signup-confirm"
                      type="password"
                      placeholder="••••••••"
                      value={signupConfirm}
                      onChange={(e) => setSignupConfirm(e.target.value)}
                      required
                    />
                  </div>
                  {signupError && <p className="text-sm text-destructive">{signupError}</p>}
                  <Button type="submit" className="w-full" disabled={signupLoading}>
                    {signupLoading ? "Creating account..." : "Create account"}
                  </Button>
                </form>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>

        <div className="border-t px-6 py-3 text-center text-xs text-muted-foreground">
          Powered by DealWing &middot; Growth OS
        </div>
      </Card>
    </div>
  );
}
