"use client";
import { useState } from "react";
import { Plus, Search, UsersRound } from "lucide-react";
import type { Technician } from "@hub/contracts";
import { useResource } from "@/lib/use-resource";
import { TechnicianCard } from "@/components/technician-card";
import { AddTechnician } from "@/components/add-technician";
import { EmptyState, ErrorNotice, Loading } from "@/components/ui";
export default function TechniciansPage() {
  const { data, error, reload } = useResource<Technician[]>("/technicians");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const terms = search.trim().toLocaleLowerCase().split(/\s+/);
  const filtered = data?.filter((t) =>
    terms.every(
      (term) =>
        t.first_name.toLocaleLowerCase().includes(term) ||
        t.last_name.toLocaleLowerCase().includes(term),
    ),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR PEOPLE, CONNECTED</div>
          <h1>Technicians</h1>
          <p className="muted">
            One place for your team and their connections.
          </p>
        </div>
        <button className="button primary" onClick={() => setAdding(true)}>
          <Plus size={18} />
          Add Technician
        </button>
      </div>
      <div className="toolbar">
        <label className="search-field">
          <Search size={18} />
          <input
            aria-label="Search technicians"
            placeholder="Search technicians…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <span className="muted count-label">
          {data
            ? `${filtered?.length} ${filtered?.length === 1 ? "technician" : "technicians"}`
            : ""}
        </span>
      </div>
      <ErrorNotice message={error} retry={reload} />
      {!data && !error ? (
        <Loading />
      ) : filtered?.length ? (
        <div className="technician-grid">
          {filtered.map((t) => (
            <TechnicianCard key={t.id} technician={t} />
          ))}
        </div>
      ) : (
        data && (
          <div className="panel">
            <EmptyState
              icon={<UsersRound size={27} />}
              title={
                search ? "No matching technicians" : "Your team starts here"
              }
            >
              <p>
                {search
                  ? "Try a different name."
                  : "Add your first technician to bring their profile and connections together."}
              </p>
              {!search && (
                <button
                  className="button primary"
                  onClick={() => setAdding(true)}
                >
                  <Plus size={16} />
                  Add Technician
                </button>
              )}
            </EmptyState>
          </div>
        )
      )}
      <div className="page-footnote">
        Technician identity is managed locally. External connections will be
        available in a future stage.
      </div>
      {adding && <AddTechnician onClose={() => setAdding(false)} />}
    </>
  );
}
