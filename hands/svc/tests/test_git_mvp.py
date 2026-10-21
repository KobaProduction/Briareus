"""MVP Git merge, public read, pagination and real local-worktree acceptance."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from modules.github.github_agent import GitHubAppClient, GitHubAgentError
from modules.github.pulls import GitHubPullClient
from modules.github.issues import GitHubIssueClient
from modules.gitlab.merge_requests import GitLabMergeRequestClient
from svc_hand.node_git import NodeGitHubClient, _canonical, _checkout, _cleanup_merged, _git


class MergeFixture(GitHubPullClient):
    def __init__(self):
        self.calls = []
        self.protected_branches = frozenset()
        self.required_checks = ()
        self.expected = "a" * 40
        self.auto_delete = False
        self.protected = False
        self.changed = False
        self.merged = True

    def _assert_allowed(self, repository):
        return repository

    def assert_required_checks(self, *args):
        return {}

    def _delete_source_branch_cas(self, repository, branch, expected_head):
        self.calls.append(("CAS_DELETE", branch, {"expected_head":expected_head}))

    def _repo_request(self, repository, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith('/pulls/1'):
            return 200, {"head": {"sha": self.expected, "ref": "feature", "repo": {"full_name": repository}},
                         "base": {"ref": "main", "repo": {"full_name": repository}}}
        if path.endswith('/pulls/1/merge'):
            return 200, {"merged": self.merged, "sha": "b" * 40}
        if '/branches/' in path:
            return 200, {"protected": self.protected}
        if '/git/ref/heads/' in path:
            return 200, {"object": {"sha": "c" * 40 if self.changed else self.expected}}
        if method == 'DELETE':
            return 204, {}
        return 200, {"default_branch": "main", "delete_branch_on_merge": self.auto_delete}


class GitMvpTests(unittest.TestCase):
    def test_merge_requires_choice_and_sha_and_pins_actual_merge(self):
        client = MergeFixture()
        with self.assertRaises(TypeError):
            client.merge_pull_request('owner/repo', 1)
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request('owner/repo', 1, False)
        result = client.merge_pull_request('owner/repo', 1, False, expected_head_sha=client.expected)
        merge = next(call for call in client.calls if call[0] == 'PUT')
        self.assertEqual(merge[2]['payload']['sha'], client.expected)
        self.assertEqual(result['source_branch_state'], 'kept')
        self.assertFalse(any(call[0] == 'CAS_DELETE' for call in client.calls))

    def test_keep_conflict_and_delete_protection(self):
        client = MergeFixture(); client.auto_delete = True
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request('owner/repo', 1, False, expected_head_sha=client.expected)
        self.assertFalse(any(call[0] == 'PUT' for call in client.calls))
        client = MergeFixture(); client.protected = True
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request('owner/repo', 1, True, expected_head_sha=client.expected)
        self.assertFalse(any(call[0] == 'PUT' for call in client.calls))

    def test_delete_only_after_confirmed_merge_and_unchanged_branch(self):
        client = MergeFixture()
        result = client.merge_pull_request('owner/repo', 1, True, expected_head_sha=client.expected)
        self.assertEqual(result['source_branch_state'], 'deleted')
        self.assertLess(next(i for i,c in enumerate(client.calls) if c[0]=='PUT'), next(i for i,c in enumerate(client.calls) if c[0]=='CAS_DELETE'))
        client = MergeFixture(); client.changed = True
        result = client.merge_pull_request('owner/repo', 1, True, expected_head_sha=client.expected)
        self.assertEqual(result['source_branch_state'], 'preserved_head_changed')
        self.assertFalse(any(c[0]=='CAS_DELETE' for c in client.calls))
        client = MergeFixture(); client.merged = False
        client.merge_pull_request('owner/repo', 1, True, expected_head_sha=client.expected)
        self.assertFalse(any(c[0]=='CAS_DELETE' for c in client.calls))

    def test_public_read_uses_selected_app_without_alias_and_never_writes(self):
        client = object.__new__(GitHubAppClient)
        client.public_only = False; client.token = ''
        with patch.object(client, '_assert_allowed', side_effect=lambda value:value), patch.object(client, '_installation_token', side_effect=GitHubAgentError('is not installed for GitHub App')), patch.object(client, '_request', side_effect=[(200, {'private': False}), (200, {'content': 'public'})]) as request:
            self.assertEqual(client._repo_request('owner/public', 'GET', '/repos/owner/public/readme')[1]['content'], 'public')
            self.assertTrue(all('token' not in call.kwargs for call in request.call_args_list))
        with patch.object(client, '_assert_allowed', side_effect=lambda value:value), patch.object(client, '_installation_token', side_effect=GitHubAgentError('is not installed for GitHub App')), patch.object(client, '_request') as request:
            with self.assertRaises(GitHubAgentError):
                client._repo_request('owner/public', 'PUT', '/repos/owner/public/contents/a', payload={})
            request.assert_not_called()

    def test_issue_next_page_survives_page_full_of_prs(self):
        client = object.__new__(GitHubIssueClient)
        client._last_response_headers = {'link': '<https://api.github.com/repos/o/r/issues?page=3&per_page=100>; rel="next"'}
        with patch.object(client, '_assert_allowed', side_effect=lambda value:value), patch.object(client, '_repo_request', return_value=(200,[{'pull_request': {}, 'number':1}])):
            result = client.list_issues('o/r', page=2, per_page=200)
        self.assertEqual(result['issues'], [])
        self.assertTrue(result['has_next']); self.assertEqual(result['next_page'],3)
        self.assertEqual(result['per_page'],100)
        self.assertEqual(result['raw_count'],1)

    def test_gitlab_merge_requires_choice_sha_and_preserves_provider_cas(self):
        from types import SimpleNamespace
        from modules.gitlab.errors import GitLabError
        client = object.__new__(GitLabMergeRequestClient)
        client.profile = SimpleNamespace(profile_id="fixture")
        client.protected_branches = frozenset()
        head = "a" * 40
        current = {"sha": head, "source_branch": "feature", "target_branch": "main",
                   "source_project_id": 1, "target_project_id": 1}
        with patch.object(client, "request", side_effect=[SimpleNamespace(data=current), SimpleNamespace(data={"state": "merged"})]) as request:
            result = client.merge_merge_request("owner/repo", 1, False, sha=head)
            payload = request.call_args.kwargs["payload"]
            self.assertEqual(payload["sha"], head)
            self.assertIs(payload["should_remove_source_branch"], False)
            self.assertEqual(result["source_branch_action"], "keep")
        with self.assertRaises(GitLabError):
            client.merge_merge_request("owner/repo", 1, True)
        with patch.object(client, "request", return_value=SimpleNamespace(data={**current, "sha":"b"*40})) as request:
            with self.assertRaises(GitLabError):
                client.merge_merge_request("owner/repo", 1, True, sha=head)
            self.assertEqual(request.call_count,1)

    def test_cas_delete_refuses_branch_updated_after_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); seed=root/'seed'; seed.mkdir()
            def git(*args):
                return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()
            git('init','--template=',seed)
            git('-C',seed,'config','user.name','Fixture');git('-C',seed,'config','user.email','fixture@example.invalid')
            (seed/'a').write_text('one');git('-C',seed,'add','.');git('-C',seed,'commit','-m','one')
            old=git('-C',seed,'rev-parse','HEAD');git('-C',seed,'branch','feature')
            remote=root/'remote.git';git('clone','--bare','--template=',seed,remote)
            client=NodeGitHubClient(token='fixture',account_id='selected');client.workspace_root=root
            (seed/'a').write_text('two');git('-C',seed,'commit','-am','two')
            new=git('-C',seed,'rev-parse','HEAD')
            # Concurrent producer recreates/advances feature after the merge read.
            git('-C',remote,'update-ref','refs/heads/feature',old)
            git('-C',seed,'push',remote,'HEAD:refs/heads/feature')
            original=_git
            def local_transport(target,*args,**kwargs):
                if args[0] != 'push':
                    return original(target,*args,**kwargs)
                rewritten=[str(remote) if item.startswith('https://github.com/') else item for item in args]
                result=subprocess.run(['git','-C',str(target),*rewritten],capture_output=True,text=True)
                if result.returncode:
                    raise ValueError('CAS rejected changed branch')
                return result.stdout
            with patch('svc_hand.node_git._git',side_effect=local_transport):
                with self.assertRaises(ValueError):
                    client._delete_source_branch_cas('owner/repo','feature',old)
                self.assertEqual(git('-C',remote,'rev-parse','refs/heads/feature'),new)
                client._delete_source_branch_cas('owner/repo','feature',new)
            absent=subprocess.run(['git','-C',str(remote),'rev-parse','--verify','refs/heads/feature'],capture_output=True)
            self.assertNotEqual(absent.returncode,0)
            self.assertEqual(list((root/'.briareus-git'/'repositories').glob('.delete-*')),[])

    def test_real_canonical_worktrees_reuse_and_preserve_dirty(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); seed=root/'seed'; seed.mkdir()
            def git(*args):
                return subprocess.run(['git',*map(str,args)],check=True,capture_output=True,text=True).stdout.strip()
            git('init','--template=',seed)
            git('-C',seed,'config','user.name','Fixture'); git('-C',seed,'config','user.email','fixture@example.invalid')
            (seed/'a.txt').write_text('initial')
            git('-C',seed,'add','.');git('-C',seed,'commit','-m','fixture')
            client=NodeGitHubClient(token='fixture',account_id='selected'); client.workspace_root=root
            url=client._expected_remote('owner/repo'); canonical=_canonical(root,url)
            git('clone','--bare','--template=',seed,canonical)
            git('-C',canonical,'remote','set-url','origin',url)
            original=_git
            def offline(target,*args,**kwargs):
                return '' if args[0]=='fetch' else original(target,*args,**kwargs)
            with patch('svc_hand.node_git._git',side_effect=offline):
                one=_checkout(client,'owner/repo','agents/a',url,'','',mode='git',branch='agent/a')
                two=_checkout(client,'owner/repo','agents/b',url,'','',mode='git',branch='agent/b')
                reused=_checkout(client,'owner/repo','agents/a',url,'','',mode='git')
                self.assertEqual(one['canonical_repository'],two['canonical_repository']);self.assertTrue(reused['reused'])
                self.assertNotEqual(one['branch'],two['branch'])
                with self.assertRaises(ValueError):
                    _checkout(client,'owner/repo','agents/a',url,'','',mode='snapshot',overwrite=True)
                head=git('-C',root/'agents/a','rev-parse','HEAD')
                (root/'agents/a'/'a.txt').write_text('dirty work')
                kept=_cleanup_merged(client,'owner/repo','agent/a',head)
                self.assertEqual(kept['preserved_worktrees'],['agents/a']);self.assertTrue((root/'agents/a').exists())
                removed=_cleanup_merged(client,'owner/repo','agent/b',head)
                self.assertEqual(removed['removed_worktrees'],['agents/b']);self.assertFalse((root/'agents/b').exists())
                self.assertEqual((root/'agents/a'/'a.txt').read_text(),'dirty work')
                self.assertTrue(canonical.exists())
                with self.assertRaises(Exception):
                    _checkout(client,'owner/repo','../other-project',url,'','',mode='git')


if __name__ == '__main__':
    unittest.main()


class DefaultRefFreshnessTests(unittest.TestCase):
    def test_checkout_selects_updated_remote_default_not_bare_head(self):
        from types import SimpleNamespace
        from contextlib import nullcontext
        import svc_hand.node_git as module
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);canonical=root/"canonical.git";canonical.mkdir()
            calls=[]
            def git(target,*args,**kwargs):
                calls.append(args)
                if args[:3]==("remote","get-url","origin"):return "https://github.com/o/r.git"
                if args[:3]==("ls-remote","--symref","origin"):return "ref: refs/heads/main\tHEAD\nabc\tHEAD"
                return ""
            client=SimpleNamespace(workspace_root=root,protected_branches=frozenset())
            with patch.object(module,"_canonical",return_value=canonical),patch.object(module,"_repository_lock",return_value=nullcontext()),patch.object(module,"_git",side_effect=git):
                module._checkout(client,"o/r","agent","https://github.com/o/r.git","","",mode="git",branch="feature")
            add=next(args for args in calls if args[:2]==("worktree","add"))
            self.assertEqual(add[-1],"refs/remotes/origin/main")
