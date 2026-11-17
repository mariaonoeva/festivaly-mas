import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Gigs · Festivaly" };

export default function GigsPage() {
  return (
    <main className="dataset-page">
      <h1>Gigs</h1>
      <p className="dataset-intro">
        Gig matching is in development. Festivaly currently has festival
        listings, and gig listings will appear once we have venue and booking data.
      </p>
      <div className="dataset-notes">
        <section>
          <h2>Find places to play</h2>
          <p>
            The idea is to help bands find clubs, small stages, and local
            promoters in Czechia and Slovakia. You’ll be able to pick your
            genres and explore venues and booking opportunities by city.
          </p>
        </section>
        <section>
          <h2>See how to get booked</h2>
          <p>
            Where an organiser publishes a booking contact or application link,
            the listing will point you to it. If an opportunity has a date or
            deadline, we plan to show it alongside the listing.
          </p>
          <p><Link href="/festivals">Browse festivals meanwhile</Link></p>
        </section>
      </div>
    </main>
  );
}
