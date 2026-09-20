# Estock mobile

The Flutter client for shop floor work: record a sale, look up stock, check who
owes what — with or without a connection.

## Running it

```bash
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1   # Android emulator
flutter run --dart-define=API_BASE_URL=http://localhost:8000/api/v1  # iOS simulator
```

`API_BASE_URL` is read at build time. On a physical device, point it at the
machine running the API (`http://192.168.x.x:8000/api/v1`), and make sure that
host is listed in the API's `CORS_ORIGINS`.

```bash
flutter test        # 31 tests
flutter analyze
flutter build apk --release --dart-define=API_BASE_URL=https://api.yourshop.et/api/v1
```

## How offline works

A shop with no signal still has customers. The app is built so that selling
never depends on the network.

**What is held on the device**

- The session, so the app opens straight into work after a restart.
- The catalogue — names, prices, last-known quantities — refreshed whenever
  there is a connection. Quantities from the cache are labelled as last known;
  the server decides what actually fits the stock on hand.
- An **outbox** of operations captured while offline.

**What is not held on the device**

Credit balances. Showing a stale balance to someone deciding whether to extend
more credit would be worse than showing nothing, so the credit screen asks for a
connection and says so.

**The conflict policy**

The server stays the authority. A sale captured offline is *provisional* until
the server accepts it, and the interface says so rather than implying it is
already in the books.

Every queued operation carries an idempotency key generated **when the operation
was captured**, not when it is sent. The server deduplicates on that key, so
replaying an operation it already accepted returns the same record instead of
creating a second one — which is what makes retrying after an ambiguous failure
safe.

On replay there are three outcomes:

| Outcome | What happens |
| --- | --- |
| Accepted | Marked synced, with the document number the server assigned. |
| Refused on its merits (4xx) | Marked **rejected** and shown to a person. Two phones both sold the last unit offline; the second now fails with `insufficient_stock`. The app never silently drops it and never invents a correction — what to do about a sale that cannot be posted is a business decision. |
| Could not reach the server | Stays pending, retried on reconnect and every two minutes. |

Sales replay strictly oldest-first, so the server draws stock down in the order
the shop actually sold.

Signing out keeps the outbox: unsynced work is not thrown away because someone
signed out.

## Layout

```
lib/
  main.dart                     entry point, routes
  core/
    api_client.dart             HTTP, auth header, error mapping
    app_state.dart              session, cached catalogue, outbox wiring
    money.dart                  ETB, quantities, dates, due-date wording
    theme.dart                  colour and shape
    offline/
      outbox.dart               durable queue of captured operations
      sync_service.dart         replay, and the conflict policy above
      catalogue_cache.dart      local copy of the catalogue
  models/                       product, session
  screens/                      sign-in, shell, home, sale, stock, shop, credit, more, pending
  widgets/                      stat tiles, status chips, offline banner
test/                           31 tests
```

## Fonts

Noto Sans and Noto Sans Ethiopic are bundled rather than fetched from a CDN.
Two reasons, both specific to this product: shops work on intermittent
connections, and Amharic needs Ethiopic glyphs that a Latin-only default font
does not carry. Without this the app renders *no text at all* when the font CDN
is unreachable — which is exactly the situation it is built for.
