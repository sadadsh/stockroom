# Microsoft Store Distribution

## Decision

Microsoft Store is Stockroom's only public Windows installation and update
channel. GitHub remains the source, issue, release-note, and verification home,
but it does not publish an unsigned public installer. This avoids presenting a
download that Windows blocks or that asks each person to install a private trust
certificate.

The existing direct TUF/App Installer implementation remains a tested internal
capability. It is disabled in Store packages so one installed app has one update
authority. GitHub Pages may retain the reserved feed location, but a Store package
must never poll or activate that feed.

## Store Identity

Partner Center owns the following immutable identity:

- Product name: `Stockroom`
- Store ID: `9NQ6HP17PH4H`
- Package identity name: `Sadad.Stockroom`
- Publisher: `CN=6586C41B-410B-4C94-8631-F025DB362E47`
- Publisher display name: `Sadad`
- Package family name: `Sadad.Stockroom_p16bsq5x1dh0a`
- Store page: `https://apps.microsoft.com/detail/9NQ6HP17PH4H`

The Store-specific package manifest must use these values exactly. Development
and fixture identities remain separate and unchanged.

Store package versions use `1.0.<build>.0`. Microsoft reserves the fourth
component for Store use, so the source package must always leave it at zero.
Every component remains within the MSIX `0..65535` limit, and the first component
must remain nonzero.

## Delivery Channels

### Microsoft Store

- Publishes the installable MSIX.
- Applies Microsoft's trusted signature during certification.
- Owns public installation, update discovery, download, activation, rollback,
  uninstall, and Store reputation.
- Shows `Microsoft Store` as the update authority inside Stockroom.
- Disables Stockroom's direct TUF/App Installer polling and activation paths.

### GitHub

- Hosts source, issues, release notes, SBOM, build evidence, and checksums.
- Links the primary Install action to the Store page.
- May retain development or fixture artifacts only when their non-production
  status is unmistakable.
- Does not publish an unsigned artifact as the normal user download.

## Build Boundary

Add a Store configuration to the existing package contract instead of forking a
second packager. It reuses the frozen native host, worker, frontend, assets, SBOM,
and package validation. The configuration changes only:

- Store-owned manifest identity.
- Store-owned update channel.
- Removal of App Installer and TUF feed activation from the shipped Store package.
- Creation of one Store-upload artifact after the canonical Windows gate passes.

The Store artifact must be reproducible before Store signing. Its build evidence
records the exact Git revision, frontend content identity, package identity,
package version, and `microsoft-store` update channel. No certificate, password,
TUF online key, or Partner Center credential may enter the artifact.

## Product Behavior

Settings shows `Updates From Microsoft Store` for Store packages. The action opens
the reserved Store product page. Direct-feed states, retry controls, rollback
controls, and App Installer language are not rendered in that channel. Source and
development builds keep their existing truthful update state.

The host rejects a Store package that contains a direct production feed contract.
It also rejects a Store identity paired with a non-Store update channel. These are
packaging errors, not runtime fallbacks.

## Store Listing

The first submission uses:

- Free availability.
- Windows desktop devices supported by the existing x64 package.
- A concise listing that describes component-library, CAD-model, project, and
  Design Studio workflows without claiming unverified provider automation.
- A public privacy policy describing distributor API calls, user-directed provider
  pages, local library storage, and the absence of Stockroom-operated analytics.
- Current light and dark screenshots captured from the Store candidate package.
- Honest additional testing instructions for selecting or creating a library.

No submission is sent for certification until its package, listing, privacy policy,
age rating, screenshots, and testing instructions have been reviewed together.

## Failure And Recovery

- A Store packaging failure leaves the existing source and development products
  unchanged.
- A rejected Store submission creates no direct-feed fallback and does not alter an
  installed development build.
- A Store update failure remains owned by Store and Windows. Stockroom reports the
  Store authority and offers the Store page; it does not start a competing updater.
- Personal drafts, applied designs, and user libraries stay outside release
  directories and survive Store updates under the existing persistence contract.

## Verification

Acceptance requires:

- Package-contract RED/GREEN tests for exact Store identity and forbidden mixed
  update authorities.
- Native-host tests proving Store builds never invoke direct-feed update work.
- Frontend tests for Store-specific Settings copy and action.
- The canonical Windows gate.
- Two byte-identical unsigned Store package builds.
- Partner Center package validation before upload.
- Review of listing copy, privacy policy, assets, and screenshots.
- Explicit confirmation immediately before uploading the package and immediately
  before submitting the completed listing for certification.

## Primary References

- [Microsoft Store MSIX signing](https://learn.microsoft.com/en-us/windows/msix/package/sign-msix-package-guide)
- [Upload MSIX packages](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/upload-app-packages)
- [MSIX package requirements and versioning](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-package-requirements)
- [Microsoft Store certification](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/app-certification-process)

## Rejected Alternatives

- **Unsigned GitHub installer:** free, but Windows blocks or warns and the result is
  not the simple installation experience Stockroom requires.
- **Self-signed public installer:** free, but every person must install a trust root.
- **Two active public updaters:** creates conflicting state and recovery ownership.
- **Paid Artifact Signing:** technically suitable, but rejected because the owner
  chose a zero-cost distribution path.
