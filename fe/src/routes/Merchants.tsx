import { useQuery } from "@tanstack/react-query";
import { Async } from "@/components/Async";
import { PageHeader } from "@/components/AppLayout";
import { Badge } from "@/components/ui/primitives";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/services/api";
import { fmtNum } from "@/lib/utils";

export function Merchants() {
  const q = useQuery({ queryKey: ["merchants"], queryFn: () => api.get<any>("/api/merchants") });
  return (
    <div>
      <PageHeader title="Merchants" sub="Signals are suppressed when merchant resolution is too sparse to trust." />
      <Async q={q}>
        {(d) => (
          <div className="space-y-6">
            <Card>
              <CardHeader><CardTitle className="text-base">Profiles</CardTitle></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <THead><TR><TH>Merchant</TH><TH>Posts</TH><TH>Views/day</TH><TH>Median price</TH></TR></THead>
                  <TBody>
                    {(d.profiles || []).map((p: any) => (
                      <TR key={p.merchant}>
                        <TD className="font-medium">{p.merchant}</TD>
                        <TD>{p.posts}</TD>
                        <TD>{p.avg_views_per_day != null ? Math.round(p.avg_views_per_day) : "—"}</TD>
                        <TD>{p.price_median != null ? `₹${fmtNum(p.price_median)}` : "—"}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </CardContent>
            </Card>

            <section>
              <h2 className="mb-3 text-lg font-semibold">Opportunities</h2>
              <div className="space-y-3">
                {(d.opportunities || []).map((o: any, i: number) => (
                  <Card key={i}>
                    <CardContent className="p-4">
                      <div className="mb-1 flex items-center gap-2">
                        {o.kind && <Badge>{o.kind}</Badge>}
                        {o.merchant && <Badge variant="primary">{o.merchant}</Badge>}
                      </div>
                      <p>{o.description}</p>
                    </CardContent>
                  </Card>
                ))}
                {(d.opportunities || []).length === 0 && (
                  <p className="text-sm text-muted-foreground">No merchant opportunities surfaced.</p>
                )}
              </div>
            </section>
          </div>
        )}
      </Async>
    </div>
  );
}
