import { Card, CardDescription, CardFooter, CardHeader } from "./ui/card";

const sentimentColor = {
  positive: "#22c55e",
  negative: "#ef4444",
  neutral: "#94a3b8",
};

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
    <Card
      className={`mx-auto w-full max-w-sm comment-card`}
      style={{
        borderLeft: `4px solid ${sentimentColor[sentiment as keyof typeof sentimentColor]}`,
        borderTop: `1px solid ${sentimentColor[sentiment as keyof typeof sentimentColor]}`,
        borderBottom: `1px solid ${sentimentColor[sentiment as keyof typeof sentimentColor]}`,
        borderRight: `1px solid ${sentimentColor[sentiment as keyof typeof sentimentColor]}`,
      }}
    >
      <CardHeader>{comment}</CardHeader>
      <CardFooter>
        <div className="flex flex-row justify-between w-full">
          <CardDescription>
            Score: <SentimentScore sentiment={sentiment} score={score} />
          </CardDescription>
          <CardDescription>Sentiment: {sentiment}</CardDescription>
        </div>
      </CardFooter>
    </Card>
  );
}

const SentimentScore = ({
  sentiment,
  score,
}: {
  sentiment: string;
  score: number;
}) => {
  const color =
    sentiment === "positive"
      ? "#22c55e"
      : sentiment === "negative"
        ? "#ef4444"
        : "#94a3b8";
  return (
    <span style={{ color }}>
      {sentiment === "positive" ? "+" : sentiment === "negative" ? "-" : ""}
      {score}
    </span>
  );
};
