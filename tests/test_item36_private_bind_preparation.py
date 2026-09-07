import hashlib
import unittest

from tools.prepare_item36_private_bind import render_image_update, render_private_bind


UNIT = (
    "[Service]\n"
    "ExecStart=/usr/bin/docker run --pull=never --name=noteai-api-c "
    "--read-only --cap-drop=ALL --env-file=/etc/noteai/api.env "
    "--publish=127.0.0.1:8000:8000 registry.example.invalid/api@sha256:"
    + "a" * 64 + "\nRestart=no\n"
).encode()


class Item36PrivateBindPreparationTests(unittest.TestCase):
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
