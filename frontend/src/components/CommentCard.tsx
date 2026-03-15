import { Card, CardDescription, CardFooter, CardHeader } from "./ui/card";

export default function CommentCard({
  comment,
  score,
  sentiment,
}: {
  comment: string;
  score: number;
  sentiment: string;
}) {
  return (
    <Card className="mx-auto w-full max-w-sm">
      <CardHeader>{comment}</CardHeader>
      <CardFooter>
        <div className="flex flex-row justify-between w-full">
          <CardDescription>Score: {score}</CardDescription>
          <CardDescription>Sentiment: {sentiment}</CardDescription>
        </div>
      </CardFooter>
    </Card>
  );
}
