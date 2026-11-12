import { FormEvent, useCallback, useEffect, useState } from 'react';

type Product = { id: string; name: string; description: string; price: string; stock: number; category: string };
type Order = { id: string; status: string; total: string; customer_email: string; created_at: string; items: { product_id: string; quantity: number }[] };
type ProductDraft = Omit<Product, 'id' | 'price'> & { price: number };

const emptyDraft: ProductDraft = { name: '', description: '', price: 10, stock: 10, category: 'general' };
let reportedIncident = false;

async function reportIncident(kind: 'error' | 'latency', detail: string): Promise<void> {
  if (reportedIncident) return;
  reportedIncident = true;
  try {
    const response = await fetch('/api/v1/incidents', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: kind === 'latency' ? 'North Market catalog is responding slowly' : 'North Market customers cannot load the catalog',
        description: `${detail}. Automatically detected from the standalone Shop app.`,
        service: 'shopapi', severity: kind === 'latency' ? 'high' : 'critical', source: 'manual', scenario_key: null,
      }),
    });
    if (!response.ok) return;
    const incident = await response.json() as { id: string };
    await fetch(`/api/v1/incidents/${incident.id}/investigations`, { method: 'POST' });
  } catch { reportedIncident = false; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/shopapi${path}`, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!response.ok) {
    const message = `${response.status} · ${(await response.json().catch(() => ({})) as { detail?: string }).detail ?? 'ShopAPI request failed'}`;
    if (response.status >= 500) void reportIncident('error', `${init?.method ?? 'GET'} ${path} returned ${message}`);
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [view, setView] = useState<'catalog' | 'manage' | 'orders'>('catalog');
  const [draft, setDraft] = useState<ProductDraft>(emptyDraft);
  const [editing, setEditing] = useState<string | null>(null);
  const [cart, setCart] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [latency, setLatency] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const started = performance.now(); setBusy(true); setError(null);
    try {
      const [catalog, orderData] = await Promise.all([request<{ items: Product[] }>('/products'), request<{ items: Order[] }>('/orders')]);
      const elapsed = Math.round(performance.now() - started);
      setProducts(catalog.items); setOrders(orderData.items); setLatency(elapsed);
      if (elapsed > 800) {
        void reportIncident('latency', `GET /shopapi/products took ${elapsed} ms`);
      } else {
        reportedIncident = false;
      }
    } catch (reason) { setLatency(Math.round(performance.now() - started)); setError(reason instanceof Error ? reason.message : 'Unavailable'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const saveProduct = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { await request(`/products${editing ? `/${editing}` : ''}`, { method: editing ? 'PATCH' : 'POST', body: JSON.stringify(draft) }); setDraft(emptyDraft); setEditing(null); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Save failed'); setBusy(false); }
  };
  const editProduct = (product: Product) => { setDraft({ ...product, price: Number(product.price) }); setEditing(product.id); setView('manage'); };
  const deleteProduct = async (id: string) => { if (!confirm('Delete this product?')) return; try { await request(`/products/${id}`, { method: 'DELETE' }); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Delete failed'); } };
  const checkout = async () => {
    if (!cart.length) return; setBusy(true); setError(null);
    const quantities = new Map<string, number>(); cart.forEach((item) => quantities.set(item.id, (quantities.get(item.id) ?? 0) + 1));
    try { await request('/orders', { method: 'POST', body: JSON.stringify({ idempotency_key: crypto.randomUUID(), customer_email: 'demo@north.market', items: [...quantities].map(([product_id, quantity]) => ({ product_id, quantity })) }) }); setCart([]); setView('orders'); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Checkout failed'); setBusy(false); }
  };
  const updateOrder = async (id: string, status: string) => { await request(`/orders/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }); await load(); };
  const deleteOrder = async (id: string) => { if (!confirm('Delete this order?')) return; await request(`/orders/${id}`, { method: 'DELETE' }); await load(); };

  return <div className="shell">
    <header><div><b>north/market</b><span>ShopAPI</span></div><nav><button className={view === 'catalog' ? 'on' : ''} onClick={() => setView('catalog')}>Store</button><button className={view === 'manage' ? 'on' : ''} onClick={() => setView('manage')}>Products</button><button className={view === 'orders' ? 'on' : ''} onClick={() => setView('orders')}>Orders</button></nav><button className="bag" onClick={checkout}>Bag · {cart.length}</button></header>
    <div className={`status ${error ? 'bad' : ''}`}><i /> <span>{busy ? 'ShopAPI request running…' : error ? `Customer impact · ${error}` : `ShopAPI healthy · ${latency} ms`}</span><button onClick={() => void load()}>Refresh</button></div>
    <main>
      {view === 'catalog' && <><section className="hero"><span>LIVE COMMERCE DEMO</span><h1>Simple goods.<br/><em>Real API calls.</em></h1><p>Every click reaches ShopAPI. Inject an incident in Ravel and the customer impact appears here.</p></section>{error ? <Failure error={error} latency={latency} retry={load}/> : <div className="grid">{products.map((p, i) => <article key={p.id}><div className={`art a${i % 4}`}>{['◇','○','△','□'][i % 4]}</div><section><div><b>{p.name}</b><small>{p.category} · {p.stock} left</small></div><strong>${Number(p.price).toFixed(2)}</strong></section><button disabled={!p.stock} onClick={() => setCart((items) => [...items, p])}>Add to bag</button></article>)}</div>}</>}
      {view === 'manage' && <section className="workspace"><div><span>CATALOG CRUD</span><h1>{editing ? 'Edit product' : 'New product'}</h1><p>Create and update inventory through the real ShopAPI.</p><form onSubmit={saveProduct}>{(['name','description','category'] as const).map((key) => <label key={key}>{key}<input value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} required={key !== 'description'}/></label>)}<div className="pair"><label>price<input type="number" min="0.01" step="0.01" value={draft.price} onChange={(e) => setDraft({ ...draft, price: Number(e.target.value) })}/></label><label>stock<input type="number" min="0" value={draft.stock} onChange={(e) => setDraft({ ...draft, stock: Number(e.target.value) })}/></label></div><button disabled={busy}>{editing ? 'Save changes' : 'Create product'}</button>{editing && <button type="button" className="ghost" onClick={() => { setEditing(null); setDraft(emptyDraft); }}>Cancel</button>}</form></div><div className="table"><h2>Products <span>{products.length}</span></h2>{products.map((p) => <div className="row" key={p.id}><div><b>{p.name}</b><small>{p.stock} in stock · ${p.price}</small></div><button onClick={() => editProduct(p)}>Edit</button><button className="danger" onClick={() => void deleteProduct(p.id)}>Delete</button></div>)}</div></section>}
      {view === 'orders' && <section className="orders"><div><span>ORDER CRUD</span><h1>Orders</h1><p>Read, update, and delete customer orders.</p></div><div className="table">{orders.length === 0 && <div className="empty">No orders yet.</div>}{orders.map((o) => <div className="order" key={o.id}><div><b>#{o.id.slice(0,8)}</b><small>{o.customer_email} · {o.items?.length ?? 0} item(s) · ${o.total}</small></div><select value={o.status} onChange={(e) => void updateOrder(o.id, e.target.value)}><option>pending</option><option>confirmed</option><option>shipped</option><option>cancelled</option></select><button className="danger" onClick={() => void deleteOrder(o.id)}>Delete</button></div>)}</div></section>}
    </main>
  </div>;
}

function Failure({ error, latency, retry }: { error: string; latency: number; retry: () => Promise<void> }) {
  return <div className="failure"><span>503 / CUSTOMER IMPACT</span><h2>The store is having trouble.</h2><p><code>GET /shopapi/products</code> failed after {latency} ms.<br/>{error}</p><button onClick={() => void retry()}>Try again</button><a href="http://127.0.0.1:5173">Open Ravel →</a></div>;
}
