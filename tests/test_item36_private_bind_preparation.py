import hashlib
from pathlib import Path
import unittest

from tools.prepare_item36_private_bind import render_image_update, render_private_bind, render_payment_namespace


UNIT = (
    "[Service]\n"
    "ExecStart=/usr/bin/docker run --pull=never --name=noteai-api-c "
    "--read-only --cap-drop=ALL --env-file=/etc/noteai/api.env "
    "--publish=127.0.0.1:8000:8000 registry.example.invalid/api@sha256:"
    + "a" * 64 + "\nRestart=no\n"
).encode()


class Item36PrivateBindPreparationTests(unittest.TestCase):
    def test_payment_first_enable_uses_actual_api_namespace_and_preserves_absence(self):
        source = (Path(__file__).parent / "fixtures/item36-api-f.service").read_bytes()
        template = (Path(__file__).resolve().parents[1] / "deploy/production/systemd/noteai-payment.service.template").read_bytes()
        candidate, rollback = render_payment_namespace(
            source, expected_sha256=hashlib.sha256(source).hexdigest(), template=template,
            callback_enabled=True,
        )
        self.assertIsNone(rollback)
        self.assertIn(b"--network=container:noteai-api-f", candidate)
        self.assertIn(b"Environment=NOTEAI_PAYMENT_CALLBACK_ENABLED=1\n", candidate)
        self.assertIn(b"@@NOTEAI_PAYMENT_IMAGE@@", candidate)
        self.assertNotIn(b"@@NOTEAI_API_CONTAINER@@", candidate)
        self.assertNotIn(b"--publish", candidate)

    def test_payment_image_binding_and_existing_disabled_unit_exact_rollback(self):
        template = (Path(__file__).resolve().parents[1] / "deploy/production/systemd/noteai-payment.service.template").read_bytes()
        image = "registry.example.invalid/payment@sha256:" + "c" * 64
        prior = b"[Service]\n# separately reviewed disabled prior unit\n"
        candidate, rollback = render_payment_namespace(
            UNIT, expected_sha256=hashlib.sha256(UNIT).hexdigest(), template=template,
            payment_image=image, prior_unit=prior, prior_sha256=hashlib.sha256(prior).hexdigest(),
        )
        self.assertEqual(rollback, prior)
        self.assertIn(b"--network=container:noteai-api-c", candidate)
        self.assertEqual(candidate.count(image.encode()), 2)
        self.assertNotIn(b"@@", candidate)
        for options in ({"template": template + b"# drift\n"}, {"payment_image": "payment:latest"},
                        {"callback_enabled": "1"}, {"prior_unit": prior, "prior_sha256": "0" * 64}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                render_payment_namespace(UNIT, expected_sha256=hashlib.sha256(UNIT).hexdigest(),
                                         **{"template": template, **options})

    def test_actual_reviewed_api_f_unit_can_bind_and_preserve_exact_rollback(self):
        source = (Path(__file__).parent / "fixtures/item36-api-f.service").read_bytes()
        digest = "f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936"
        self.assertEqual(hashlib.sha256(source).hexdigest(), digest)
        candidate, rollback = self.render(source, address="10.42.11.166", digest=digest)
        self.assertEqual(rollback, source)
        self.assertEqual(candidate.replace(b"10.42.11.166:8000:8000", b"127.0.0.1:8000:8000"), source)
        old_image = source.decode().split("--log-opt max-file=2 ")[1].splitlines()[0]
        new_image = "registry.example.invalid/api@sha256:" + "b" * 64
        updated, original = render_image_update(
            source, expected_sha256=digest, expected_image=old_image, candidate_image=new_image,
        )
        self.assertEqual(original, source)
        self.assertEqual(updated.replace(new_image.encode(), old_image.encode()), source)

    def test_only_reviewed_quote_and_explicit_unprivileged_form_are_allowed(self):
        source = (Path(__file__).parent / "fixtures/item36-api-f.service").read_bytes()
        for before, after in ((b"--privileged=false", b"--privileged"),
                              (b"--privileged=false", b"--privileged=true"),
                              (b"default_transaction_read_only=on", b"default_transaction_read_only=off"),
                              (b"statement_timeout=5000", b"statement_timeout=$TIMEOUT"),
                              (b'1000" --mount', b'1000"--mount'),
                              (b"--mount", b"--env PGOPTIONS= --mount"),
                              (b"--mount", b"--env=PGOPTIONS= --mount"),
                              (b'"PGOPTIONS=', b"'PGOPTIONS=")):
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.render(source=source.replace(before, after))

    def render(self, source=UNIT, address="10.0.1.12", digest=None):
        return render_private_bind(
            source, expected_sha256=digest or hashlib.sha256(source).hexdigest(), private_ip=address
        )

    def test_only_exact_binding_changes_and_rollback_is_original_bytes(self):
        candidate, rollback = self.render()
        self.assertEqual(rollback, UNIT)
        self.assertEqual(candidate.replace(b"10.0.1.12:8000:8000", b"127.0.0.1:8000:8000"), UNIT)

    def test_rejects_drift_multiple_ports_host_network_and_mutable_image(self):
        with self.assertRaisesRegex(ValueError, "unit_source_binding"):
            self.render(digest="b" * 64)
        for source in (
            UNIT.replace(b"--read-only", b"--network=host --read-only"),
            UNIT.replace(b"--read-only", b"--net=host --read-only"),
            UNIT.replace(b"--read-only", b"--net  host --read-only"),
            UNIT.replace(b"--read-only", b"--network='host' --read-only"),
            UNIT.replace(b"--read-only", b"--privileged=true --read-only"),
            UNIT.replace(b"--read-only", b"--publish-all=true --read-only"),
            UNIT.replace(b"--read-only", b"-p0.0.0.0:9000:9000 --read-only"),
            UNIT.replace(b"--read-only", b"-p 9000:9000 --read-only"),
            UNIT.replace(b"127.0.0.1:8000:8000", b"0.0.0.0:8000:8000"),
            UNIT.replace(b"@sha256:" + b"a" * 64, b":latest"),
            UNIT.replace(b"--read-only", b"--read-only $EXTRA_ARGS"),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.render(source)

    def test_exact_argument_span_preserves_labels_and_comment_with_same_text(self):
        source = UNIT.replace(b"--read-only", b"--label=prior=127.0.0.1:8000:8000 --read-only")
        comment = b"# " + source.splitlines()[1] + b"\n"
        candidate, rollback = self.render(comment + source)
        self.assertEqual(rollback, comment + source)
        self.assertTrue(candidate.startswith(comment))
        self.assertIn(b"--label=prior=127.0.0.1:8000:8000", candidate)
        self.assertIn(b"--publish=10.0.1.12:8000:8000", candidate)

    def test_compact_short_publish_argument_is_changed_exactly(self):
        source = UNIT.replace(b"--publish=", b"-p")
        candidate, _rollback = self.render(source)
        self.assertIn(b"-p10.0.1.12:8000:8000", candidate)

    def test_rejects_public_loopback_ipv6_and_shell_input(self):
        for address in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "100.64.0.1", "::1", "10.0.1.1;false"):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "private_ipv4_required"):
                self.render(address=address)

    def test_image_update_preserves_port_labels_and_exact_rollback(self):
        original = "registry.example.invalid/api@sha256:" + "a" * 64
        candidate = "registry.example.invalid/api@sha256:" + "c" * 64
        for address in (b"127.0.0.1", b"10.0.1.12"):
            source = UNIT.replace(b"127.0.0.1", address).replace(
                b"--read-only", f"--label=prior={original} --read-only".encode()
            )
            source = f"# prior image {original}\n".encode() + source
            updated, rollback = render_image_update(
                source, expected_sha256=hashlib.sha256(source).hexdigest(),
                expected_image=original, candidate_image=candidate,
            )
            self.assertEqual(rollback, source)
            self.assertEqual(updated.replace(candidate.encode(), original.encode()), source)
            self.assertIn(b"--publish=" + address + b":8000:8000", updated)
            self.assertEqual(updated.count(original.encode()), 2)

    def test_image_update_rejects_wrong_source_mutable_injection_and_public_bind(self):
        original = "registry.example.invalid/api@sha256:" + "a" * 64
        candidate = "registry.example.invalid/api@sha256:" + "c" * 64
        for source, expected, new_image, digest in (
            (UNIT, candidate, candidate, None),
            (UNIT, original, candidate, "b" * 64),
            (UNIT, original, original, None),
            (UNIT, original, "registry.example.invalid/api:latest", None),
            (UNIT, original, candidate + " --privileged", None),
            (UNIT, original, "https://" + candidate, None),
            (UNIT, original, "-" + candidate, None),
            (UNIT.replace(b"127.0.0.1", b"0.0.0.0"), original, candidate, None),
            (UNIT.replace(b"--read-only", b"-p9000:9000 --read-only"), original, candidate, None),
        ):
            with self.subTest(expected=expected, candidate=new_image), self.assertRaises(ValueError):
                render_image_update(
                    source, expected_sha256=digest or hashlib.sha256(source).hexdigest(),
                    expected_image=expected, candidate_image=new_image,
                )

    def test_rejects_image_looking_app_argument_and_publish_looking_option_value(self):
        original = "registry.example.invalid/api@sha256:" + "a" * 64
        candidate = "registry.example.invalid/api@sha256:" + "c" * 64
        for source in (
            UNIT.replace(original.encode(), f"{candidate} {original}".encode()),
            UNIT.replace(b"--publish=", b"--label -p"),
            UNIT.replace(b"--read-only", b"--unknown-option --read-only"),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                render_image_update(
                    source, expected_sha256=hashlib.sha256(source).hexdigest(),
                    expected_image=original, candidate_image=candidate,
                )
            with self.assertRaises(ValueError):
                self.render(source=source)


if __name__ == "__main__":
    unittest.main()
