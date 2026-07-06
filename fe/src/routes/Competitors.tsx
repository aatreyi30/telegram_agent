import { useQuery } from "@tanstack/react-query";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";

export function Competitors() {
  const q = useQuery({ queryKey: ["competitors"], queryFn: () => api.get<any>("/api/competitors") });
  return (
    <div>
      <PageHeader title="Competitors" sub="Patterns worth acting on — most-similar competitors weighted highest, cross-checked against your own data." />
      <Async q={q}>
        {(d) => (
          <div className="space-y-6">
            <Card>
              <CardHeader><CardTitle className="text-base">Profiles</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <THead><TR><TH>Competitor</TH><TH>Posts</TH><TH>Similarity to us</TH><TH>Peak hour</TH></TR></THead>
                  <TBody>
                    {(d.profiles || []).map((p: any) => (
                      <TR key={p.competitor}>
                        <TD className="font-medium">{p.competitor}</TD>
                        <TD>{p.posts}</TD>
                        <TD>{p.similarity_to_us != null ? p.similarity_to_us.toFixed(2) : "—"}</TD>
                        <TD>{p.top_hour_ist != null ? `${p.top_hour_ist}:00 IST` : "—"}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </CardContent>
            </Card>

            <section>
              <h2 className="mb-3 text-lg font-semibold">Signals &amp; opportunities</h2>
              <div className="space-y-3">
                {(d.signals || []).map((s: any, i: number) => (
                  <Card key={i} className="border-l-4 border-l-warning">
                    <CardContent className="p-4">
                      <div className="mb-1 flex items-center gap-2">
                        <Badge variant="warning">{s.type}</Badge>
                        {s.competitor && <Badge>{s.competitor}</Badge>}
                      </div>
                      <p>{s.description}</p>
                    </CardContent>
                  </Card>
                ))}
                {(d.signals || []).length === 0 && (
                  <p className="text-sm text-muted-foreground">No competitor signals (need ≥20 posts per competitor).</p>
                )}
              </div>
            </section>
          </div>
        )}
      </Async>
    </div>
  );
}
